"""
Async EventBus to decouple message passing between modules.
Supports topics, fan-out subscribers, and queue buffering.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List

logger = logging.getLogger("twitch_auto_clipper.event_bus")


class EventBus:
    """Barramento de eventos assíncrono pub/sub."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Any], Coroutine[Any, Any, None]]]] = {}
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._running = True

    def subscribe(self, topic: str, handler: Callable[[Any], Coroutine[Any, Any, None]]) -> None:
        """Registra um callback assíncrono para ser executado quando um evento é publicado no tópico."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)
        logger.debug(f"Handler registrado no tópico: {topic}")

    def create_queue(self, topic: str, maxsize: int = 1000) -> asyncio.Queue:
        """Cria uma fila assíncrona desacoplada que recebe todos os eventos publicados no tópico."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        if topic not in self._queues:
            self._queues[topic] = []
        self._queues[topic].append(q)
        return q

    async def publish(self, topic: str, event: Any) -> None:
        """Publica um evento para todos os callbacks e filas registrados no tópico."""
        # Envia para queues
        if topic in self._queues:
            for q in self._queues[topic]:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"Queue cheia para o tópico {topic}. Descartando evento mais antigo.")
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except Exception:
                        pass

        # Dispara handlers assíncronos
        if topic in self._subscribers:
            tasks = [asyncio.create_task(handler(event)) for handler in self._subscribers[topic]]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
