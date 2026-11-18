"""
Mock Social Uploader implementation.
Simulates network upload, progress updates, and API responses for YouTube Shorts, TikTok, and Instagram Reels.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from core.models import ClipMetadata, UploadResult
from .base import BaseSocialUploader

logger = logging.getLogger("twitch_auto_clipper.mock_uploader")


class MockSocialUploader(BaseSocialUploader):
    """Uploader mock para testes sem necessidade de chaves reais de API."""

    def __init__(self, platform: str = "youtube", simulated_latency: float = 1.0) -> None:
        self._platform = platform.lower()
        self.simulated_latency = simulated_latency

    @property
    def platform_name(self) -> str:
        return self._platform

    async def upload(self, clip: ClipMetadata) -> UploadResult:
        """Simula processo de upload com barra de progresso em log e retorno de URL mock."""
        logger.info(f"[{self.platform_name.upper()}] Iniciando upload de {clip.clip_id}...")

        # Simula envio de chunks / latência de rede
        steps = 3
        for step in range(1, steps + 1):
            await asyncio.sleep(self.simulated_latency / steps)
            pct = int((step / steps) * 100)
            logger.debug(f"[{self.platform_name.upper()}] Progresso do upload: {pct}%")

        random_id = uuid.uuid4().hex[:11]
        urls = {
            "youtube": f"https://youtube.com/shorts/{random_id}",
            "tiktok": f"https://www.tiktok.com/@twitchclips/video/{random_id}",
            "instagram": f"https://www.instagram.com/reel/{random_id}/",
        }

        post_url = urls.get(self.platform_name, f"https://mock-social.com/posts/{random_id}")

        logger.info(f"[{self.platform_name.upper()}] Upload concluído com sucesso! URL: {post_url}")

        return UploadResult(
            platform=self.platform_name,
            success=True,
            post_id=random_id,
            post_url=post_url,
            error_message=None,
            published_at=datetime.now(timezone.utc),
        )


class MultiPlatformUploader:
    """Orquestrador que distribui o clipe para todas as redes sociais ativas."""

    def __init__(self, uploaders: Optional[List[BaseSocialUploader]] = None) -> None:
        self.uploaders = uploaders or []

    def add_uploader(self, uploader: BaseSocialUploader) -> None:
        self.uploaders.append(uploader)

    async def upload_all(self, clip: ClipMetadata) -> List[UploadResult]:
        """Dispara uploads em paralelo para todas as plataformas configuradas."""
        if not self.uploaders:
            logger.warning("Nenhum uploader configurado.")
            return []

        tasks = [uploader.upload(clip) for uploader in self.uploaders]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results: List[UploadResult] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                uploader_name = self.uploaders[i].platform_name
                logger.error(f"Erro no upload para {uploader_name}: {res}")
                final_results.append(
                    UploadResult(
                        platform=uploader_name,
                        success=False,
                        error_message=str(res),
                        published_at=datetime.now(timezone.utc),
                    )
                )
            else:
                final_results.append(res)

        return final_results
