"""
Abstract base class for hype detectors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from core.models import ChatMessage, HypeEvent


class BaseHypeDetector(ABC):
    """Contrato base para detecção de momentos de hype."""

    @abstractmethod
    def process_message(self, message: ChatMessage) -> Optional[HypeEvent]:
        """Processa uma mensagem e retorna HypeEvent se um momento de pico for atingido."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reseta contadores internos e histórico da janela deslizante."""
        pass
