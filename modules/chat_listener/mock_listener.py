"""
Mock implementation of ChatListener for development and isolated testing.
Generates realistic chat activity and can simulate hype spikes on demand.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional
from core.models import ChatMessage
from .base import BaseChatListener


DEFAULT_MOCK_USERS = [
    "csgo_fan_99", "pog_master", "tribo_gaules", "gamer_pro_br",
    "clip_maker", "fallen_god", "stream_lurker", "sub_twelve_months",
    "hype_train_conductor", "fps_enjoyer", "chat_spammer", "mod_pedro"
]

NORMAL_MESSAGES = [
    "salve tribo!",
    "qual é a mira que ele usa?",
    "partida tá insana hoje",
    "boa tarde chat",
    "gg demais",
    "quem ta ganhando?",
    "o time dele ta jogando bem",
    "vai comecar o proximo mapa?",
    "aquele round foi tenso",
    "respeita a historia",
]

HYPE_BURST_MESSAGES = [
    "POGGGGGGGGGGGGGGGGGGGGGG",
    "CLIPAAAAAAAAAAAAAAAA",
    "JOGOU O FINO DO CS",
    "QUE TIRO FOI ESSE WTF???",
    "OMEGALUL KEKW",
    "MEU DEUS DO CEU POGCHAMP",
    "INSANOOOOOOOOOOOOOOOOOOOOOO",
    "CLIP IT QUICK POGGERS",
    "GGGGGGGGGGGGGGGGGGGGGGGGGG",
    "JA VAI PRO TIKTOK ESSE CLIPE",
    "1v4 CLUTCH GOD",
]

HYPE_EMOTES = ["PogChamp", "KEKW", "LUL", "BibleThump", "monkaS", "EZ", "Clap"]


class MockChatListener(BaseChatListener):
    """Simulador de chat com suporte a picos programados de hype."""

    def __init__(
        self,
        channel: str = "gaules",
        msg_interval: float = 0.8,
        simulate_hype_after: Optional[int] = 5,
        hype_burst_count: int = 15,
    ) -> None:
        self.channel = channel
        self.msg_interval = msg_interval
        self.simulate_hype_after = simulate_hype_after
        self.hype_burst_count = hype_burst_count
        self._running = False
        self._message_count = 0
        self._queue: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._generator_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Inicia a rotina geradora de mensagens em background."""
        self._running = True
        self._generator_task = asyncio.create_task(self._generate_loop())

    async def stop(self) -> None:
        """Pára a geração de mensagens."""
        self._running = False
        if self._generator_task:
            self._generator_task.cancel()
            try:
                await self._generator_task
            except asyncio.CancelledError:
                pass

    async def trigger_hype_spike(self, count: int = 15) -> None:
        """Gera manualmente uma rajada instantânea de mensagens com palavras-chave de hype."""
        for _ in range(count):
            msg = ChatMessage(
                author=random.choice(DEFAULT_MOCK_USERS),
                text=random.choice(HYPE_BURST_MESSAGES),
                timestamp=datetime.now(timezone.utc),
                emotes=[random.choice(HYPE_EMOTES)],
                bits=random.choice([0, 0, 100, 500]),
                is_subscriber=random.choice([True, False, True]),
            )
            await self._queue.put(msg)
            await asyncio.sleep(0.08)  # Rajada rápida (~12 msgs/sec)

    async def _generate_loop(self) -> None:
        """Loop contínuo de geração de chat."""
        try:
            while self._running:
                self._message_count += 1

                # Dispara pico programado se configurado
                if (
                    self.simulate_hype_after is not None
                    and self._message_count == self.simulate_hype_after
                ):
                    await self.trigger_hype_spike(self.hype_burst_count)
                    await asyncio.sleep(self.msg_interval)
                    continue

                # Mensagem normal de rotina
                msg = ChatMessage(
                    author=random.choice(DEFAULT_MOCK_USERS),
                    text=random.choice(NORMAL_MESSAGES),
                    timestamp=datetime.now(timezone.utc),
                    emotes=[] if random.random() > 0.3 else [random.choice(HYPE_EMOTES)],
                    bits=100 if random.random() > 0.9 else 0,
                    is_subscriber=random.choice([True, False]),
                )
                await self._queue.put(msg)
                await asyncio.sleep(self.msg_interval)
        except asyncio.CancelledError:
            pass

    async def stream(self) -> AsyncIterator[ChatMessage]:
        """Consome o fluxo de mensagens geradas."""
        while self._running or not self._queue.empty():
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                yield msg
                self._queue.task_done()
            except asyncio.TimeoutError:
                if not self._running:
                    break
