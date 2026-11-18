"""
Moving Average Hype Detector.
Calculates the moving average of messages every 5 seconds.
When a spike exceeds 3x the normal moving average, saves the last 40 messages to JSON
and emits a 'Clipe Detectado' event with the exact timestamp.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, List, Optional, Tuple
from core.models import ChatMessage, HypeEvent, HypeScoreBreakdown
from .base import BaseHypeDetector

logger = logging.getLogger("twitch_auto_clipper.moving_average_detector")


class MovingAverageHypeDetector(BaseHypeDetector):
    """
    Detector que calcula a média móvel de mensagens a cada 5 segundos.
    Dispara 'Clipe Detectado' ao identificar pico > 3x a média normal
    e persiste as últimas 40 mensagens em JSON.
    """

    def __init__(
        self,
        channel: str = "gaules",
        interval_seconds: float = 5.0,
        spike_multiplier: float = 3.0,
        history_window_intervals: int = 12,  # 12 intervalos de 5s = 60s de média móvel normal
        min_baseline: float = 1.0,           # Baseline mínima para evitar divisão por zero
        min_spike_messages: int = 3,         # Quantidade mínima de msgs/5s para considerar um pico
        cooldown_seconds: float = 15.0,
        events_dir: Path | str = "./storage/events",
    ) -> None:
        self.channel = channel
        self.interval_seconds = interval_seconds
        self.spike_multiplier = spike_multiplier
        self.history_window_intervals = history_window_intervals
        self.min_baseline = min_baseline
        self.min_spike_messages = min_spike_messages
        self.cooldown_seconds = cooldown_seconds
        self.events_dir = Path(events_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)

        # Buffer contínuo das últimas 40 mensagens
        self._recent_messages: Deque[ChatMessage] = deque(maxlen=40)

        # Mensagens recebidas no intervalo atual de 5 segundos
        self._current_interval_messages: List[ChatMessage] = []

        # Histórico de contagem de mensagens dos intervalos anteriores para média móvel normal
        self._history: Deque[int] = deque(maxlen=history_window_intervals)

        # Controle temporal
        self._last_interval_time: Optional[datetime] = None
        self._last_clip_time: Optional[datetime] = None

    def reset(self) -> None:
        """Limpa o buffer e o histórico de médias móveis."""
        self._recent_messages.clear()
        self._current_interval_messages.clear()
        self._history.clear()
        self._last_interval_time = None
        self._last_clip_time = None

    @property
    def normal_moving_average(self) -> float:
        """Calcula o valor atual da média móvel normal de mensagens por intervalo."""
        if not self._history:
            return self.min_baseline
        return max(self.min_baseline, sum(self._history) / len(self._history))

    @property
    def recent_messages(self) -> List[ChatMessage]:
        """Retorna as mensagens atualmente armazenadas no buffer (até 40)."""
        return list(self._recent_messages)

    def process_message(self, message: ChatMessage) -> Optional[HypeEvent]:
        """
        Recebe uma mensagem de chat, armazena no buffer de 40 mensagens
        e verifica se a janela de 5 segundos deve ser avaliada.
        """
        now = message.timestamp
        self._recent_messages.append(message)
        self._current_interval_messages.append(message)

        if self._last_interval_time is None:
            self._last_interval_time = now
            return None

        elapsed = (now - self._last_interval_time).total_seconds()
        if elapsed >= self.interval_seconds:
            return self.evaluate_interval(now)

        return None

    def evaluate_interval(self, current_time: Optional[datetime] = None) -> Optional[HypeEvent]:
        """
        Executa a avaliação da média móvel a cada 5 segundos.
        Se houver pico > 3x a média normal, salva JSON e emite o evento 'Clipe Detectado'.
        """
        now = current_time or datetime.now(timezone.utc)
        count = len(self._current_interval_messages)
        self._current_interval_messages = []
        self._last_interval_time = now

        normal_avg = self.normal_moving_average
        spike_ratio = count / normal_avg

        logger.debug(
            f"Intervalo de 5s: {count} msgs | Média Normal: {normal_avg:.2f} msgs/5s | Ratio: {spike_ratio:.2f}x"
        )

        event: Optional[HypeEvent] = None

        # Condição de disparo: pico superior a 3x a média normal
        if count >= self.min_spike_messages and spike_ratio >= self.spike_multiplier:
            # Verifica cooldown para evitar duplicatas em rajadas contínuas
            in_cooldown = False
            if self._last_clip_time is not None:
                since_last = (now - self._last_clip_time).total_seconds()
                if since_last < self.cooldown_seconds:
                    logger.debug(
                        f"Pico detectado ({spike_ratio:.1f}x), mas em cooldown ({since_last:.1f}s < {self.cooldown_seconds}s)"
                    )
                    in_cooldown = True

            if not in_cooldown:
                self._last_clip_time = now
                event = self._trigger_clip_detected(now, count, normal_avg, spike_ratio)

        # Adiciona a contagem do intervalo ao histórico da média móvel
        self._history.append(count)

        return event

    def _trigger_clip_detected(
        self,
        exact_timestamp: datetime,
        current_count: int,
        normal_average: float,
        spike_ratio: float,
    ) -> HypeEvent:
        """Salva as últimas 40 mensagens em JSON e gera o HypeEvent com timestamp exato."""
        last_40 = list(self._recent_messages)
        timestamp_slug = exact_timestamp.strftime("%Y%m%d_%H%M%S_%f")
        json_filename = f"clipe_detectado_{timestamp_slug}.json"
        json_path = self.events_dir / json_filename

        payload = {
            "event": "Clipe Detectado",
            "timestamp": exact_timestamp.isoformat(),
            "channel": self.channel,
            "metrics": {
                "interval_seconds": self.interval_seconds,
                "current_interval_messages": current_count,
                "normal_moving_average": round(normal_average, 2),
                "spike_ratio": round(spike_ratio, 2),
                "threshold_multiplier": self.spike_multiplier,
            },
            "total_messages_saved": len(last_40),
            "messages": [msg.to_dict() for msg in last_40],
        }

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Últimas {len(last_40)} mensagens salvas em JSON: {json_path}")
        except Exception as e:
            logger.error(f"Erro ao salvar JSON do clipe detectado: {e}")

        reason = (
            f"Pico de {current_count} msgs/5s ({spike_ratio:.1f}x superior à média normal "
            f"de {normal_average:.1f} msgs/5s)"
        )
        logger.info(f"🚨 EVENTO: Clipe Detectado! [{exact_timestamp.isoformat()}] - {reason}")

        return HypeEvent(
            event_name="Clipe Detectado",
            score=round(spike_ratio, 2),
            reason=reason,
            streamer_channel=self.channel,
            timestamp=exact_timestamp,
            suggested_duration=30.0,
            pre_roll_seconds=15.0,
            json_path=str(json_path.resolve()),
            spike_multiplier=round(spike_ratio, 2),
            recent_messages_count=len(last_40),
            breakdown=HypeScoreBreakdown(
                messages_per_sec=round(current_count / self.interval_seconds, 2),
                total_score=round(spike_ratio, 2),
            ),
        )
