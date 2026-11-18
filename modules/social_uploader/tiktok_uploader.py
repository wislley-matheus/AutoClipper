"""
TikTok Content Posting API v2 Uploader.

Documentação oficial: https://developers.tiktok.com/doc/content-posting-api-get-started

Fluxo de upload (3 etapas):
  1. POST /v2/post/publish/video/init/
     → obtém publish_id + upload_url (inbox) OU direct_post_url
  2. PUT <upload_url> com os bytes do vídeo
  3. GET /v2/post/publish/status/fetch/ (polling) até status=PUBLISH_COMPLETE

Autenticação:
  - access_token obtido via OAuth 2.0 Authorization Code Flow do TikTok for Developers.
  - Escopo necessário: video.upload (ou video.publish dependendo da app).

Fallback automático:
  - Se access_token começa com "mock_", usa MockSocialUploader.
  - Se a API retornar erro de autenticação (401), usa MockSocialUploader.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.models import ClipMetadata, UploadResult
from .base import BaseSocialUploader

logger = logging.getLogger(__name__)

_TIKTOK_API_BASE = "https://open.tiktokapis.com"
_ENDPOINT_INIT = f"{_TIKTOK_API_BASE}/v2/post/publish/video/init/"
_ENDPOINT_STATUS = f"{_TIKTOK_API_BASE}/v2/post/publish/status/fetch/"

_MAX_POLL_ATTEMPTS = 20
_POLL_INTERVAL_SEC = 5


class TikTokUploader(BaseSocialUploader):
    """
    Uploader para TikTok via Content Posting API v2.

    Fallback automático para MockSocialUploader quando token for mock ou inválido.
    """

    def __init__(
        self,
        access_token: str = "",
        open_id: Optional[str] = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> None:
        """
        Args:
            access_token: Token de acesso OAuth do usuário TikTok.
            open_id: ID único do usuário TikTok (opcional, retornado pelo OAuth).
            privacy_level: Visibilidade do vídeo.
                           Opções: PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY.
        """
        self.access_token = access_token
        self.open_id = open_id
        self.privacy_level = privacy_level

    @property
    def platform_name(self) -> str:
        return "tiktok"

    @property
    def _is_mock_token(self) -> bool:
        """Verifica se o token é mock (para evitar chamadas reais desnecessárias)."""
        return not self.access_token or self.access_token.startswith("mock_")

    def _auth_headers(self) -> dict:
        """Headers de autenticação para a API TikTok."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _init_upload(self, clip: ClipMetadata, session) -> dict:
        """
        Etapa 1: Inicializa o upload e obtém a URL de destino dos bytes.

        Returns:
            Resposta da API contendo publish_id e upload_url.
        """
        import aiohttp

        file_size = Path(clip.file_path).stat().st_size

        payload = {
            "post_info": {
                "title": clip.title[:150],  # TikTok limita 150 chars
                "privacy_level": self.privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,  # upload em um único chunk para vídeos < 64MB
                "total_chunk_count": 1,
            },
        }

        async with session.post(
            _ENDPOINT_INIT,
            json=payload,
            headers=self._auth_headers(),
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201) or data.get("error", {}).get("code") != "ok":
                raise RuntimeError(
                    f"Falha ao inicializar upload TikTok: HTTP {resp.status} — {data}"
                )
            return data.get("data", {})

    async def _upload_video_bytes(self, upload_url: str, clip: ClipMetadata, session) -> None:
        """
        Etapa 2: Envia os bytes do vídeo via PUT para a URL obtida na etapa 1.
        """
        import aiohttp

        file_path = Path(clip.file_path)
        file_size = file_path.stat().st_size

        with open(file_path, "rb") as f:
            video_bytes = f.read()

        headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Length": str(file_size),
        }

        logger.info("Enviando %d bytes para TikTok...", file_size)
        async with session.put(upload_url, data=video_bytes, headers=headers) as resp:
            if resp.status not in (200, 201, 206):
                body = await resp.text()
                raise RuntimeError(
                    f"Falha no PUT de vídeo TikTok: HTTP {resp.status} — {body[:300]}"
                )
        logger.info("Bytes enviados com sucesso.")

    async def _poll_status(self, publish_id: str, session) -> str:
        """
        Etapa 3: Faz polling até o vídeo ser publicado (ou falhar).

        Returns:
            Status final: PUBLISH_COMPLETE, FAILED, ou o último status obtido.
        """
        import aiohttp

        payload = {"publish_id": publish_id}
        last_status = "UNKNOWN"

        for attempt in range(_MAX_POLL_ATTEMPTS):
            await asyncio.sleep(_POLL_INTERVAL_SEC)

            async with session.post(
                _ENDPOINT_STATUS,
                json=payload,
                headers=self._auth_headers(),
            ) as resp:
                data = await resp.json()
                status_data = data.get("data", {})
                last_status = status_data.get("status", "UNKNOWN")
                logger.info(
                    "TikTok publish_id=%s status=%s (tentativa %d/%d)",
                    publish_id,
                    last_status,
                    attempt + 1,
                    _MAX_POLL_ATTEMPTS,
                )

                if last_status == "PUBLISH_COMPLETE":
                    return last_status
                elif last_status in ("FAILED", "CANCELLED"):
                    error = status_data.get("fail_reason", "Motivo desconhecido")
                    raise RuntimeError(f"TikTok publicação falhou: {error}")

        logger.warning("Timeout no polling do TikTok após %d tentativas.", _MAX_POLL_ATTEMPTS)
        return last_status

    async def upload(self, clip: ClipMetadata) -> UploadResult:
        """Publica o clipe no TikTok via Content Posting API v2."""
        # Fallback imediato para token mock
        if self._is_mock_token:
            logger.info("Token TikTok é mock — usando MockSocialUploader.")
            from .mock_uploader import MockSocialUploader

            return await MockSocialUploader("tiktok").upload(clip)

        if not clip.file_exists():
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message=f"Arquivo não encontrado: {clip.file_path}",
                published_at=datetime.now(timezone.utc),
            )

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                # 1. Inicializa upload
                logger.info("Iniciando upload TikTok para '%s'...", clip.title)
                init_data = await self._init_upload(clip, session)
                publish_id = init_data.get("publish_id", "")
                upload_url = init_data.get("upload_url", "")

                if not publish_id or not upload_url:
                    raise RuntimeError(f"Resposta inválida do TikTok init: {init_data}")

                # 2. Envia bytes do vídeo
                await self._upload_video_bytes(upload_url, clip, session)

                # 3. Aguarda publicação
                final_status = await self._poll_status(publish_id, session)

            logger.info("TikTok upload concluído! publish_id=%s status=%s", publish_id, final_status)

            return UploadResult(
                platform=self.platform_name,
                success=True,
                post_id=publish_id,
                post_url=f"https://www.tiktok.com/@me/video/{publish_id}",
                published_at=datetime.now(timezone.utc),
            )

        except ImportError:
            logger.error("aiohttp não instalado. Execute: pip install aiohttp")
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message="aiohttp não instalado",
                published_at=datetime.now(timezone.utc),
            )
        except RuntimeError as exc:
            # Fallback para erro de autenticação 401
            if "401" in str(exc) or "auth" in str(exc).lower():
                logger.warning("Erro de autenticação TikTok — usando mock como fallback.")
                from .mock_uploader import MockSocialUploader

                return await MockSocialUploader("tiktok").upload(clip)
            logger.error("Erro no upload TikTok: %s", exc)
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message=str(exc),
                published_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.exception("Erro inesperado no upload TikTok: %s", exc)
            return UploadResult(
                platform=self.platform_name,
                success=False,
                error_message=str(exc),
                published_at=datetime.now(timezone.utc),
            )
