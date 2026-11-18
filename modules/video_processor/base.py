"""
Abstract base class for video processors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from core.models import ClipMetadata, HypeEvent


class BaseVideoProcessor(ABC):
    """Contrato base para geração e edição de clipes."""

    @abstractmethod
    async def create_clip(self, hype_event: HypeEvent) -> ClipMetadata:
        """Corta, formata para formato vertical e salva o clipe baseado no HypeEvent."""
        pass
