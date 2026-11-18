"""
Social Uploader — publicação de clipes no YouTube Shorts e TikTok.

Uploaders disponíveis:
  - YouTubeUploader: OAuth 2.0 + YouTube Data API v3 (upload resumível).
  - TikTokUploader: Content Posting API v2 (3 etapas: init → PUT → polling).
  - MockSocialUploader: Simulação sem credenciais (para testes).
  - MultiPlatformUploader: Orquestra múltiplos uploaders em paralelo.
"""
from .base import BaseSocialUploader
from .mock_uploader import MockSocialUploader, MultiPlatformUploader
from .youtube_uploader import YouTubeUploader
from .tiktok_uploader import TikTokUploader

__all__ = [
    "BaseSocialUploader",
    "MockSocialUploader",
    "MultiPlatformUploader",
    "YouTubeUploader",
    "TikTokUploader",
]
