"""
Twitch IRC Chat Listener implementation.
Connects directly to irc.chat.twitch.tv via raw asyncio socket.
Supports anonymous read-only access (justinfan) or authenticated OAuth tokens.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from core.models import ChatMessage
from .base import BaseChatListener

logger = logging.getLogger("twitch_auto_clipper.twitch_listener")

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667
MSG_PATTERN = re.compile(r"^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #(\w+) :(.*)$")


class TwitchIRCListener(BaseChatListener):
    """Ouvinte de chat conectado via protocolo IRC nativo da Twitch."""

    def __init__(
        self,
        channel: str,
        nickname: str = "justinfan98765",
        token: str = "oauth:mock_token",
    ) -> None:
        self.channel = channel.lower().replace("#", "")
        self.nickname = nickname
        self.token = token if token.startswith("oauth:") else f"oauth:{token}"
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._running = False
        self._queue: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._listen_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Conecta ao servidor IRC da Twitch e entra no canal."""
        logger.info(f"Conectando ao chat da Twitch para o canal #{self.channel}...")
        self._reader, self._writer = await asyncio.open_connection(IRC_HOST, IRC_PORT)
        self._running = True

        # Handshake IRC
        self._writer.write(f"PASS {self.token}\r\n".encode("utf-8"))
        self._writer.write(f"NICK {self.nickname}\r\n".encode("utf-8"))
        self._writer.write(f"JOIN #{self.channel}\r\n".encode("utf-8"))
        await self._writer.drain()

        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info(f"Conectado com sucesso ao canal #{self.channel} via IRC.")

    async def stop(self) -> None:
        """Fecha a conexão com o servidor IRC."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        logger.info("Desconectado do chat da Twitch.")

    async def _listen_loop(self) -> None:
        """Lê mensagens do socket e responde aos PINGs do servidor."""
        while self._running and self._reader:
            try:
                line_bytes = await self._reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()

                # Responde ao keep-alive PING da Twitch
                if line.startswith("PING"):
                    pong_resp = line.replace("PING", "PONG") + "\r\n"
                    if self._writer:
                        self._writer.write(pong_resp.encode("utf-8"))
                        await self._writer.drain()
                    continue

                match = MSG_PATTERN.match(line)
                if match:
                    author, channel, text = match.groups()
                    msg = ChatMessage(
                        author=author,
                        text=text,
                        timestamp=datetime.now(timezone.utc),
                    )
                    await self._queue.put(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro na leitura do chat IRC: {e}")
                await asyncio.sleep(2)

    async def stream(self) -> AsyncIterator[ChatMessage]:
        """Consome mensagens do chat."""
        while self._running or not self._queue.empty():
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield msg
                self._queue.task_done()
            except asyncio.TimeoutError:
                if not self._running:
                    break
