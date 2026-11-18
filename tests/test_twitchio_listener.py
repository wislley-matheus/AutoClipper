"""Tests for TwitchIOListener."""
import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from core.models import ChatMessage
from modules.chat_listener.twitchio_listener import TwitchIOListener


class TestTwitchIOListener(unittest.IsolatedAsyncioTestCase):

    async def test_twitchio_listener_initialization(self):
        listener = TwitchIOListener(
            channel="gaules",
            client_id="mock_id_123",
            client_secret="mock_secret_456",
            token="oauth:mock_token_789",
        )
        self.assertEqual(listener.channel, "gaules")
        self.assertEqual(listener.client_id, "mock_id_123")
        self.assertEqual(listener.client_secret, "mock_secret_456")
        self.assertEqual(listener.token, "oauth:mock_token_789")

    async def test_twitchio_message_normalization(self):
        """Testa se a conversão do objeto ChatMessage do TwitchIO para o DTO do sistema é correta."""
        listener = TwitchIOListener(channel="gaules")

        # Cria mock do payload do TwitchIO
        mock_twitch_msg = MagicMock()
        mock_twitch_msg.id = "twitch_msg_999"
        mock_twitch_msg.text = "QUE JOGADA FOI ESSA POG"
        mock_twitch_msg.timestamp = datetime.now(timezone.utc)

        mock_chatter = MagicMock()
        mock_chatter.name = "fallen_fan"
        mock_twitch_msg.chatter = mock_chatter

        mock_badge = MagicMock()
        mock_badge.name = "subscriber"
        mock_twitch_msg.badges = [mock_badge]

        mock_cheer = MagicMock()
        mock_cheer.bits = 500
        mock_twitch_msg.cheer = mock_cheer

        mock_emote = MagicMock()
        mock_emote.name = "PogChamp"
        mock_twitch_msg.emotes = [mock_emote]

        # Processa mensagem
        await listener._handle_twitchio_message(mock_twitch_msg)

        # Consome da queue
        msg = await asyncio.wait_for(listener._queue.get(), timeout=1.0)

        self.assertIsInstance(msg, ChatMessage)
        self.assertEqual(msg.id, "twitch_msg_999")
        self.assertEqual(msg.author, "fallen_fan")
        self.assertEqual(msg.text, "QUE JOGADA FOI ESSA POG")
        self.assertTrue(msg.is_subscriber)
        self.assertEqual(msg.bits, 500)
        self.assertIn("PogChamp", msg.emotes)


if __name__ == "__main__":
    unittest.main()
