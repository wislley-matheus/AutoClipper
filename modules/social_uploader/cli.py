"""
Standalone CLI runner for social_uploader module.
Allows testing distribution across YouTube, TikTok, and Instagram with mock or live credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import get_settings
from core.models import ClipMetadata
from modules.social_uploader.mock_uploader import MockSocialUploader, MultiPlatformUploader
from modules.social_uploader.youtube_uploader import YouTubeUploader
from modules.social_uploader.tiktok_uploader import TikTokUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("social_uploader.cli")


async def run_uploader(platforms: list[str], real: bool = False) -> None:
    settings = get_settings()

    # Cria metadados de um clipe simulado para teste
    fake_clip = ClipMetadata(
        clip_id="test_clip_manual_123",
        file_path="/tmp/test_clip.mp4",
        title="MOMENTO INCRIVEL NA TWITCH #Shorts",
        description="Clipe teste automatizado pelo twitch-auto-clipper.\n\n#gaming #twitch #shorts",
        tags=["gaming", "twitch", "shorts"],
        duration=15.0,
        resolution=(1080, 1920),
        created_at=datetime.now(timezone.utc),
        hype_score=9.8,
    )

    multi = MultiPlatformUploader()

    for p in platforms:
        if real and p == "youtube":
            secrets = Path(settings.youtube_client_secrets_file)
            if secrets.exists():
                logger.info("Usando YouTubeUploader REAL com credenciais em '%s'.", secrets)
                multi.add_uploader(YouTubeUploader(
                    client_secrets_file=str(secrets),
                    privacy_status=settings.youtube_privacy_status,
                ))
            else:
                logger.warning("Credenciais YouTube não encontradas — usando mock.")
                multi.add_uploader(MockSocialUploader(platform=p, simulated_latency=0.8))
        elif real and p == "tiktok":
            token = settings.tiktok_access_token
            if not token.startswith("mock_"):
                logger.info("Usando TikTokUploader REAL com access_token configurado.")
                multi.add_uploader(TikTokUploader(access_token=token))
            else:
                logger.warning("TikTok access_token é mock — usando mock uploader.")
                multi.add_uploader(MockSocialUploader(platform=p, simulated_latency=0.8))
        else:
            multi.add_uploader(MockSocialUploader(platform=p, simulated_latency=0.8))

    modo = "REAL" if real else "MOCK"
    print("\n" + "=" * 60)
    print(f" Testando Social Uploader [{modo}]")
    print(f" Plataformas: {', '.join(platforms)}")
    print(f" Título:      {fake_clip.title}")
    print("=" * 60 + "\n")

    results = await multi.upload_all(fake_clip)

    print("\n" + "=" * 60)
    print(" [RESULTADOS DE PUBLICAÇÃO]")
    for res in results:
        status_icon = "✅" if res.success else "❌"
        print(f" {status_icon} [{res.platform.upper()}] Sucesso: {res.success}")
        if res.post_url:
            print(f"    URL: {res.post_url}")
        if res.error_message:
            print(f"    Erro: {res.error_message}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste isolado do Social Uploader")
    parser.add_argument(
        "--platforms",
        nargs="+",
        default=["youtube", "tiktok", "instagram"],
        help="Lista de plataformas para envio (ex: youtube tiktok)",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        default=False,
        help="Usa uploaders reais quando credenciais estiverem disponíveis (default: mock)",
    )
    args = parser.parse_args()

    asyncio.run(run_uploader(args.platforms, real=args.real))


if __name__ == "__main__":
    main()
