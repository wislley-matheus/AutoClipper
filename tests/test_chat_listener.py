"""Tests for chat_listener module."""
import unittest
from modules.chat_listener.mock_listener import MockChatListener
from core.models import ChatMessage


class TestChatListener(unittest.IsolatedAsyncioTestCase):

    async def test_mock_chat_listener_streams_messages(self):
        listener = MockChatListener(
            channel="testchannel",
            msg_interval=0.05,
            simulate_hype_after=None,
        )
        await listener.start()

        messages = []
        async for msg in listener.stream():
            messages.append(msg)
            if len(messages) >= 5:
                break

        await listener.stop()

        self.assertEqual(len(messages), 5)
        for msg in messages:
            self.assertIsInstance(msg, ChatMessage)
            self.assertTrue(len(msg.author) > 0)
            self.assertTrue(len(msg.text) > 0)
            self.assertIsNotNone(msg.timestamp)

    async def test_mock_chat_listener_hype_spike(self):
        listener = MockChatListener(
            channel="testchannel",
            msg_interval=0.05,
            simulate_hype_after=2,
            hype_burst_count=6,
        )
        await listener.start()

        messages = []
        async for msg in listener.stream():
            messages.append(msg)
            if len(messages) >= 8:
                break

        await listener.stop()
        self.assertEqual(len(messages), 8)


if __name__ == "__main__":
    unittest.main()
