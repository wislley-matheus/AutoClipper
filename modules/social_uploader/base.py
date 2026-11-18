"""
Abstract base class for social media uploaders.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List
from core.models import ClipMetadata, UploadResult


class BaseSocialUploader(ABC):
    """Contrato base para uploaders de redes sociais."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Identificador da plataforma (ex: 'youtube', 'tiktok', 'instagram')."""
        pass

    @abstractmethod
    async def upload(self, clip: ClipMetadata) -> UploadResult:
        """Realiza o upload do clipe e retorna o resultado padronizado com link/ID."""
        pass
