"""
YouTube Shorts Uploader com OAuth 2.0 completo via YouTube Data API v3.

Fluxo de autenticação:
  1. Na primeira execução: abre browser para autenticar e salva o token.
  2. Nas execuções seguintes: carrega o token salvo e renova automaticamente.

Configuração necessária:
  - credentials/youtube_client_secret.json (baixado do Google Cloud Console)
  - Escopo: https://www.googleapis.com/auth/youtube.upload

Upload:
  - Usa MediaFileUpload com upload resumível (chunked) — robusto para arquivos grandes.
  - Define automaticamente a categoria Gaming (categoryId=20) e marca como #Shorts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.models import ClipMetadata, UploadResult
from .base import BaseSocialUploader

logger = logging.getLogger(__name__)

_YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_API_SERVICE_NAME = "youtube"
_API_VERSION = "v3"
_DEFAULT_CATEGORY_ID = "20"  # Gaming


class YouTubeUploader(BaseSocialUploader):
    """
    Uploader para YouTube Shorts via Google API Client com OAuth 2.0.

    Fallback automático para MockSocialUploader quando credenciais ausentes.
    """

    def __init__(
        self,
        client_secrets_file: str = "./credentials/youtube_client_secret.json",
        token_file: str = "./credentials/youtube_token.pkl",
        privacy_status: str = "public",
        category_id: str = _DEFAULT_CATEGORY_ID,
    ) -> None:
        self.client_secrets_file = Path(client_secrets_file)
        self.token_file = Path(token_file)
        self.privacy_status = privacy_status
        self.category_id = category_id
        self._service = None

    @property
    def platform_name(self) -> str:
        return "youtube"

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------

    def _authenticate(self):
        """
        Autentica via OAuth 2.0 InstalledAppFlow.

        - Carrega token existente do disco se disponível e válido.
        - Se expirado, tenta renovar com o refresh_token.
        - Se inexistente, abre o navegador para o fluxo de autorização.
        """
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        credentials = None

        # Tenta carregar token salvo
        if self.token_file.exists():
            try:
                with open(self.token_file, "rb") as f:
                    credentials = pickle.load(f)
                logger.info("Token OAuth do YouTube carregado de '%s'.", self.token_file)
            except Exception as exc:
                logger.warning("Falha ao carregar token salvo: %s", exc)
                credentials = None

        # Renova token expirado
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                logger.info("Token OAuth do YouTube renovado com sucesso.")
            except Exception as exc:
                logger.warning("Falha ao renovar token: %s — reautenticando.", exc)
                credentials = None

        # Fluxo de autorização completo (abre browser)
        if credentials is None or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secrets_file),
                scopes=_YOUTUBE_SCOPES,
            )
            credentials = flow.run_local_server(port=0, open_browser=True)
            logger.info("Autenticação OAuth do YouTube concluída.")

            # Persiste o token para próximas execuções
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "wb") as f:
                pickle.dump(credentials, f)
            logger.info("Token salvo em '%s'.", self.token_file)

        return credentials

    def _get_service(self):
        """Retorna o serviço autenticado da YouTube Data API v3."""
        if self._service is not None:
            return self._service

        from googleapiclient.discovery import build

        credentials = self._authenticate()
        self._service = build(
            _API_SERVICE_NAME,
            _API_VERSION,
            credentials=credentials,
            cache_discovery=False,
        )
        return self._service

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def _build_video_resource(self, clip: ClipMetadata) -> dict:
        """Monta o corpo da requisição de upload do vídeo."""
        # Adiciona #Shorts à descrição para garantir categorização no YouTube
        description = clip.description
        if "#Shorts" not in description:
            description = f"{description}\n\n#Shorts"

        # Garante que #Shorts está nas tags
        tags = list(clip.tags)
        if "Shorts" not in tags:
            tags.append("Shorts")

        return {
            "snippet": {
                "title": clip.title[:100],  # YouTube limita a 100 chars
                "description": description[:5000],
                "tags": tags[:500],  # YouTube limita a 500 tags
                "categoryId": self.category_id,
                "defaultLanguage": "pt",
            },
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

    def _upload_sync(self, clip: ClipMetadata) -> UploadResult:
        """Executa o upload síncrono (chamado em thread separada)."""
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        service = self._get_service()
        body = self._build_video_resource(clip)

        logger.info("Iniciando upload para YouTube Shorts: '%s' (%s)", clip.title, clip.file_path)

        media = MediaFileUpload(
            clip.file_path,
            mimetype="video/mp4",
            chunksize=10 * 1024 * 1024,  # 10 MB por chunk
            resumable=True,
        )

        request = service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info("Upload YouTube: %d%%", pct)

        video_id = response.get("id", "")
        logger.info("Upload concluído! Video ID: %s", video_id)

        return UploadResult(
            platform=self.platform_name,
            success=True,
            post_id=video_id,
            post_url=f"https://youtube.com/shorts/{video_id}",
            published_at=datetime.now(timezone.utc),
        )

    async def upload(self, clip: ClipMetadata) -> UploadResult:
        """Faz o upload do clipe como YouTube Short (assíncrono)."""
        # Fallback se credenciais não existem
        if not self.client_secrets_file.is_file():
            logger.warning(
                "Credenciais do YouTube não encontradas em '%s'. Usando mock.",
                self.client_secrets_file,
            )
            from .mock_uploader import MockSocialUploader

            return await MockSocialUploader("youtube").upload(clip)

        if not clip.file_exists():
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message=f"Arquivo não encontrado: {clip.file_path}",
                published_at=datetime.now(timezone.utc),
            )

        try:
            # Roda o upload síncrono em thread para não bloquear o event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._upload_sync, clip)
            return result

        except Exception as exc:
            logger.exception("Erro ao fazer upload para o YouTube: %s", exc)
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message=str(exc),
                published_at=datetime.now(timezone.utc),
            )
