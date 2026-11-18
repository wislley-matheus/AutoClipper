"""
TwitchIO Chat Listener implementation.
Connects to Twitch chat using the official TwitchIO library configured via .env variables.
Translates TwitchIO ChatMessage events into standardized core.models.ChatMessage instances.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from core.models import ChatMessage
from .base import BaseChatListener

logger = logging.getLogger("twitch_auto_clipper.twitchio_listener")

try:
    import twitchio
    HAS_TWITCHIO = True
except ImportError:
    twitchio = None  # type: ignore
    HAS_TWITCHIO = False


class TwitchIOListener(BaseChatListener):
    """Ouvinte de chat da Twitch implementado sobre a biblioteca TwitchIO."""

    def __init__(
        self,
        channel: str,
        client_id: str = "mock_twitch_client_id",
        client_secret: Optional[str] = "mock_twitch_client_secret",
        token: Optional[str] = None,
    ) -> None:
        self.channel = channel.lower().replace("#", "")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = token
        self._running = False
        self._queue: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._client: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Inicializa o cliente TwitchIO e inicia a escuta assíncrona."""
        if not HAS_TWITCHIO:
            raise RuntimeError(
                "A biblioteca 'twitchio' não está instalada. "
                "Execute 'pip install twitchio' para utilizar este listener."
            )

        logger.info(f"Iniciando TwitchIOListener para o canal #{self.channel} (Client ID: {self.client_id[:6]}...)")
        self._running = True

        # Cria instância do cliente TwitchIO
        client = twitchio.Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        self._client = client

        # Registra callback assíncrono para mensagens de chat
        @client.listen("event_message")
        async def on_message(message: twitchio.ChatMessage) -> None:
            await self._handle_twitchio_message(message)

        # Adiciona token se fornecido
        if self.token and self.token != "oauth:mock_token_here":
            try:
                raw_token = self.token.removeprefix("oauth:")
                await client.add_token(raw_token, "")
            except Exception as e:
                logger.warning(f"Não foi possível registrar o token de usuário no TwitchIO: {e}")

        # Inicia o loop de conexão em segundo plano
        self._task = asyncio.create_task(self._run_client())

    async def _run_client(self) -> None:
        """Executa a conexão do cliente TwitchIO tratando encerramento e erros."""
        try:
            if self._client:
                await self._client.start()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Erro na conexão do cliente TwitchIO: {e}")
            self._running = False

    async def _handle_twitchio_message(self, message: Any) -> None:
        """Normaliza mensagem do TwitchIO para o formato ChatMessage do sistema."""
        try:
            author_name = message.chatter.name if getattr(message, "chatter", None) else "anon"
            text_content = getattr(message, "text", "")
            msg_id = getattr(message, "id", None) or str(uuid.uuid4())
            timestamp = getattr(message, "timestamp", None) or datetime.now(timezone.utc)

            # Extração de emotes
            emotes = []
            if hasattr(message, "emotes") and message.emotes:
                emotes = [getattr(e, "name", str(e)) for e in message.emotes]

            # Bits
            bits = 0
            if hasattr(message, "cheer") and message.cheer:
                bits = getattr(message.cheer, "bits", 0)

            # Badge de assinante
            is_sub = False
            if hasattr(message, "badges") and message.badges:
                is_sub = any(getattr(b, "name", "") in ("subscriber", "founder") for b in message.badges)

            normalized = ChatMessage(
                id=str(msg_id),
                author=str(author_name),
                text=str(text_content),
                timestamp=timestamp,
                emotes=emotes,
                bits=bits,
                is_subscriber=is_sub,
            )
            await self._queue.put(normalized)
        except Exception as e:
            logger.error(f"Falha ao processar mensagem do TwitchIO: {e}")

    async def stop(self) -> None:
        """Encerra a conexão com a Twitch."""
        self._running = False
        if self._client and hasattr(self._client, "close"):
            try:
                await self._client.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"TwitchIOListener encerrado para #{self.channel}.")

    async def stream(self) -> AsyncIterator[ChatMessage]:
        """Consome mensagens do chat normalizadas."""
        while self._running or not self._queue.empty():
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                yield msg
                self._queue.task_done()
            except asyncio.TimeoutError:
                if not self._running:
                    break
