"""
Sliding-window hype detection algorithm.
Analyzes message velocity (MPS), viral keywords, emotes, and bit donations.
"""
from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional
from core.models import ChatMessage, HypeEvent, HypeScoreBreakdown
from .base import BaseHypeDetector
from .rules import HypeRuleConfig

logger = logging.getLogger("twitch_auto_clipper.hype_detector")


class SlidingWindowHypeDetector(BaseHypeDetector):
    """Detector de hype baseado em janela de tempo deslizante e pesos configuráveis."""

    def __init__(
        self,
        config: Optional[HypeRuleConfig] = None,
        channel: str = "gaules",
        clip_duration: float = 30.0,
        clip_preroll: float = 15.0,
    ) -> None:
        self.config = config or HypeRuleConfig()
        self.channel = channel
        self.clip_duration = clip_duration
        self.clip_preroll = clip_preroll

        # Fila com mensagens dentro da janela
        self._window: Deque[ChatMessage] = deque()
        self._last_trigger_time: Optional[datetime] = None

        # Regex compilada para palavras-chave
        escaped_keywords = [re.escape(k) for k in self.config.keywords]
        pattern = r"\b(" + "|".join(escaped_keywords) + r")\b"
        self._keyword_regex = re.compile(pattern, re.IGNORECASE)

    def reset(self) -> None:
        """Limpa o buffer da janela."""
        self._window.clear()
        self._last_trigger_time = None

    def process_message(self, message: ChatMessage) -> Optional[HypeEvent]:
        """Adiciona mensagem à janela deslizante, expira antigas e calcula o score."""
        now = message.timestamp
        self._window.append(message)

        # Remove mensagens mais antigas que a janela
        cutoff = now.timestamp() - self.config.window_seconds
        while self._window and self._window[0].timestamp.timestamp() < cutoff:
            self._window.popleft()

        total_msgs = len(self._window)
        if total_msgs < 2:
            return None

        # Cálculo de mensagens por segundo (MPS)
        mps = total_msgs / max(1.0, float(self.config.window_seconds))

        # Contagem de keywords, emotes, bits e subs
        keyword_hits = 0
        emotes_count = 0
        bits_donated = 0
        sub_count = 0

        for msg in self._window:
            matches = self._keyword_regex.findall(msg.text)
            keyword_hits += len(matches)
            emotes_count += len(msg.emotes)
            bits_donated += msg.bits
            if msg.is_subscriber:
                sub_count += 1

        # Cálculo do score total ponderado
        score = (
            (mps * self.config.weight_mps)
            + (keyword_hits * self.config.weight_keyword)
            + (emotes_count * self.config.weight_emote)
            + (bits_donated * self.config.weight_bits)
            + (sub_count * self.config.weight_sub)
        )

        breakdown = HypeScoreBreakdown(
            messages_per_sec=round(mps, 2),
            keyword_matches=keyword_hits,
            emotes_count=emotes_count,
            bits_donated=bits_donated,
            total_score=round(score, 2),
        )

        # Verifica se atinge os critérios de disparo
        if mps >= self.config.threshold_mps or score >= self.config.min_score:
            # Checa cooldown para evitar duplicatas em sequência
            if self._last_trigger_time is not None:
                elapsed = (now - self._last_trigger_time).total_seconds()
                if elapsed < self.config.cooldown_seconds:
                    logger.debug(
                        f"Hype detectado (score={score:.1f}), mas ignorado pelo cooldown ({elapsed:.1f}s < {self.config.cooldown_seconds}s)"
                    )
                    return None

            self._last_trigger_time = now
            reason = (
                f"Pico de {mps:.1f} msg/s com {keyword_hits} palavras de hype "
                f"e {bits_donated} bits (Score Total: {score:.1f})"
            )
            logger.info(f"🔥 MOMENTO DE HYPE DETECTADO! Razão: {reason}")

            return HypeEvent(
                score=round(score, 2),
                reason=reason,
                streamer_channel=self.channel,
                suggested_duration=self.clip_duration,
                pre_roll_seconds=self.clip_preroll,
                timestamp=now,
                breakdown=breakdown,
            )

        return None
