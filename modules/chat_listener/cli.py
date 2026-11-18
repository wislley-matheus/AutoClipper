"""
Standalone CLI runner for chat_listener module.
Allows isolated testing of chat stream generation and Twitch IRC connection.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Adiciona raiz do projeto ao path para execução direta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import get_settings
from modules.chat_listener.mock_listener import MockChatListener
from modules.chat_listener.twitch_listener import TwitchIRCListener
from modules.chat_listener.twitchio_listener import TwitchIOListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("chat_listener.cli")


async def run_listener(mode: str, channel: str, count: int, trigger_spike: bool) -> None:
    settings = get_settings()

    if mode == "mock":
        logger.info(f"Iniciando MockChatListener para canal: {channel}")
        listener = MockChatListener(
            channel=channel,
            msg_interval=0.5,
            simulate_hype_after=3 if trigger_spike else None,
            hype_burst_count=10,
        )
    elif mode == "twitchio":
        logger.info(f"Iniciando TwitchIOListener para canal: {channel}")
        listener = TwitchIOListener(
            channel=channel,
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
            token=settings.twitch_oauth_token,
        )
    else:
        logger.info(f"Iniciando TwitchIRCListener para canal: {channel}")
        listener = TwitchIRCListener(
            channel=channel,
            nickname=settings.twitch_bot_nickname,
            token=settings.twitch_oauth_token,
        )

    await listener.start()
    received = 0

    try:
        print("\n" + "=" * 60)
        print(f" Ouvindo chat ({mode.upper()}) no canal #{channel}")
        print(" Pressione Ctrl+C para encerrar...")
        print("=" * 60 + "\n")

        async for msg in listener.stream():
            received += 1
            badge = "[SUB]" if msg.is_subscriber else "     "
            bits = f"({msg.bits} bits)" if msg.bits > 0 else ""
            print(f"[{msg.timestamp.strftime('%H:%M:%S')}] {badge} {msg.author}: {msg.text} {bits}")

            if count > 0 and received >= count:
                logger.info(f"Limite de {count} mensagens atingido.")
                break
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário.")
    finally:
        await listener.stop()
        logger.info(f"Total de mensagens recebidas: {received}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste isolado do Chat Listener")
    parser.add_argument("--mode", choices=["mock", "twitch", "twitchio"], default="mock", help="Modo de execução (mock, twitch ou twitchio)")
    parser.add_argument("--channel", default="gaules", help="Nome do canal da Twitch")
    parser.add_argument("--count", type=int, default=15, help="Quantidade de mensagens para coletar (0 para infinito)")
    parser.add_argument("--spike", action="store_true", default=True, help="Simular pico de hype após 3 mensagens (apenas mock)")
    args = parser.parse_args()

    asyncio.run(run_listener(args.mode, args.channel, args.count, args.spike))


if __name__ == "__main__":
    main()
