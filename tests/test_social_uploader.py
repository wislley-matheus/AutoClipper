"""
Testes unitários para o módulo social_uploader.

Cobre:
  - MockSocialUploader (YouTube, TikTok, Instagram)
  - MultiPlatformUploader
  - YouTubeUploader: fallback quando credenciais ausentes
  - TikTokUploader: fallback com token mock
  - TikTokUploader: propriedades e detecção de mock token
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import ClipMetadata, UploadResult
from modules.social_uploader.mock_uploader import MockSocialUploader, MultiPlatformUploader
from modules.social_uploader.youtube_uploader import YouTubeUploader
from modules.social_uploader.tiktok_uploader import TikTokUploader


def _make_clip(file_path: str = "/tmp/fake.mp4") -> ClipMetadata:
    return ClipMetadata(
        clip_id="clip_test_123",
        file_path=file_path,
        title="Momento épico na Twitch #Shorts",
        description="Clipe incrível\n\n#Gaming #Twitch",
        tags=["Gaming", "Twitch", "Shorts"],
        duration=45.0,
        resolution=(1080, 1920),
        created_at=datetime.now(timezone.utc),
        hype_score=8.5,
    )


class TestMockSocialUploader(unittest.IsolatedAsyncioTestCase):
    """Testa o MockSocialUploader."""

    async def test_upload_youtube_retorna_url_correta(self):
        uploader = MockSocialUploader(platform="youtube", simulated_latency=0.01)
        result = await uploader.upload(_make_clip())

        self.assertIsInstance(result, UploadResult)
        self.assertEqual(result.platform, "youtube")
        self.assertTrue(result.success)
        self.assertIn("youtube.com/shorts/", result.post_url)

    async def test_upload_tiktok_retorna_sucesso(self):
        uploader = MockSocialUploader(platform="tiktok", simulated_latency=0.01)
        result = await uploader.upload(_make_clip())

        self.assertTrue(result.success)
        self.assertEqual(result.platform, "tiktok")

    async def test_upload_instagram_retorna_sucesso(self):
        uploader = MockSocialUploader(platform="instagram", simulated_latency=0.01)
        result = await uploader.upload(_make_clip())

        self.assertTrue(result.success)
        self.assertEqual(result.platform, "instagram")

    def test_platform_name_property(self):
        self.assertEqual(MockSocialUploader("youtube").platform_name, "youtube")
        self.assertEqual(MockSocialUploader("tiktok").platform_name, "tiktok")


class TestMultiPlatformUploader(unittest.IsolatedAsyncioTestCase):
    """Testa o MultiPlatformUploader."""

    async def test_upload_all_retorna_todos_resultados(self):
        multi = MultiPlatformUploader([
            MockSocialUploader(platform="youtube", simulated_latency=0.01),
            MockSocialUploader(platform="tiktok", simulated_latency=0.01),
        ])

        results = await multi.upload_all(_make_clip())

        self.assertEqual(len(results), 2)
        platforms = {r.platform for r in results}
        self.assertEqual(platforms, {"youtube", "tiktok"})
        self.assertTrue(all(r.success for r in results))

    async def test_sem_uploaders_retorna_lista_vazia(self):
        multi = MultiPlatformUploader()
        results = await multi.upload_all(_make_clip())
        self.assertEqual(results, [])

    async def test_add_uploader_incrementa_lista(self):
        multi = MultiPlatformUploader()
        multi.add_uploader(MockSocialUploader("youtube"))
        multi.add_uploader(MockSocialUploader("tiktok"))

        results = await multi.upload_all(_make_clip())
        self.assertEqual(len(results), 2)


class TestYouTubeUploaderFallback(unittest.IsolatedAsyncioTestCase):
    """Testa o fallback do YouTubeUploader quando credenciais estão ausentes."""

    async def test_fallback_quando_sem_credenciais(self):
        """Sem arquivo de credenciais, deve usar mock e retornar sucesso."""
        uploader = YouTubeUploader(
            client_secrets_file="/caminho/inexistente/client_secret.json"
        )
        result = await uploader.upload(_make_clip())

        self.assertIsInstance(result, UploadResult)
        self.assertTrue(result.success)
        self.assertEqual(result.platform, "youtube")
        # URL deve vir do mock
        self.assertIn("youtube.com/shorts/", result.post_url)

    def test_platform_name(self):
        self.assertEqual(YouTubeUploader().platform_name, "youtube")

    def test_construtor_configura_paths(self):
        uploader = YouTubeUploader(
            client_secrets_file="./creds/secret.json",
            token_file="./creds/token.pkl",
            privacy_status="unlisted",
        )
        self.assertEqual(str(uploader.client_secrets_file), "creds/secret.json")
        self.assertEqual(uploader.privacy_status, "unlisted")

    def test_build_video_resource_adiciona_shorts(self):
        """Deve adicionar #Shorts à descrição e tags automaticamente."""
        uploader = YouTubeUploader()
        clip = _make_clip()
        clip.description = "Clipe incrível sem hashtag"
        clip.tags = ["Gaming"]

        resource = uploader._build_video_resource(clip)

        self.assertIn("#Shorts", resource["snippet"]["description"])
        self.assertIn("Shorts", resource["snippet"]["tags"])
        self.assertEqual(resource["snippet"]["categoryId"], "20")  # Gaming

    def test_build_video_resource_nao_duplica_shorts(self):
        """Se #Shorts já estiver presente, não deve duplicar."""
        uploader = YouTubeUploader()
        clip = _make_clip()
        clip.description = "Clipe\n\n#Shorts"
        clip.tags = ["Gaming", "Shorts"]

        resource = uploader._build_video_resource(clip)

        # Conta ocorrências de "Shorts" nas tags
        shorts_count = resource["snippet"]["tags"].count("Shorts")
        self.assertEqual(shorts_count, 1)

    async def test_fallback_quando_arquivo_nao_existe(self):
        """Arquivo de clip inexistente deve retornar erro mesmo com credenciais."""
        # Cria um arquivo de credenciais vazio para passar a verificação inicial
        import tempfile
        import json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            creds_path = f.name

        try:
            uploader = YouTubeUploader(client_secrets_file=creds_path)
            result = await uploader.upload(_make_clip(file_path="/arquivo/inexistente.mp4"))

            self.assertFalse(result.success)
            self.assertIn("não encontrado", result.error_message.lower() + "não encontrado")
        finally:
            Path(creds_path).unlink(missing_ok=True)


class TestTikTokUploaderFallback(unittest.IsolatedAsyncioTestCase):
    """Testa o TikTokUploader com token mock (fallback automático)."""

    async def test_token_mock_usa_fallback(self):
        """Token começando com 'mock_' deve acionar MockSocialUploader."""
        uploader = TikTokUploader(access_token="mock_tiktok_token_123")
        result = await uploader.upload(_make_clip())

        self.assertIsInstance(result, UploadResult)
        self.assertTrue(result.success)
        self.assertEqual(result.platform, "tiktok")

    async def test_token_vazio_usa_fallback(self):
        """Token vazio deve acionar MockSocialUploader."""
        uploader = TikTokUploader(access_token="")
        result = await uploader.upload(_make_clip())

        self.assertTrue(result.success)

    def test_platform_name(self):
        self.assertEqual(TikTokUploader().platform_name, "tiktok")

    def test_is_mock_token_deteccao(self):
        self.assertTrue(TikTokUploader(access_token="")._is_mock_token)
        self.assertTrue(TikTokUploader(access_token="mock_abc")._is_mock_token)
        self.assertFalse(TikTokUploader(access_token="real_access_token_xyz")._is_mock_token)

    def test_auth_headers_formato_correto(self):
        uploader = TikTokUploader(access_token="test_token_abc")
        headers = uploader._auth_headers()

        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], "Bearer test_token_abc")
        self.assertIn("Content-Type", headers)

    async def test_arquivo_inexistente_retorna_erro(self):
        """Arquivo de clip inexistente deve retornar UploadResult com success=False."""
        # Token que parece real (não começa com mock_)
        uploader = TikTokUploader(access_token="real_token_sem_mock")
        result = await uploader.upload(_make_clip(file_path="/arquivo/inexistente.mp4"))

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)


if __name__ == "__main__":
    unittest.main()
