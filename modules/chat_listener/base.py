"""
Abstract base class for chat listeners.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator
from core.models import ChatMessage


class BaseChatListener(ABC):
    """Contrato base para ouvintes de chat."""

    @abstractmethod
    async def start(self) -> None:
        """Inicia conexão com a fonte de chat."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Encerra conexão de forma graciosa."""
        pass

    @abstractmethod
    def stream(self) -> AsyncIterator[ChatMessage]:
        """Iterador assíncrono que produz instâncias de ChatMessage conforme chegam."""
        pass
