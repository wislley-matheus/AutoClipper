"""Tests for hype_detector module."""
import unittest
from datetime import datetime, timezone
from core.models import ChatMessage, HypeEvent
from modules.hype_detector.detector import SlidingWindowHypeDetector
from modules.hype_detector.rules import HypeRuleConfig


class TestHypeDetector(unittest.TestCase):

    def test_hype_detector_normal_chat_no_trigger(self):
        config = HypeRuleConfig(
            window_seconds=10,
            threshold_mps=5.0,
            min_score=15.0,
            cooldown_seconds=30,
        )
        detector = SlidingWindowHypeDetector(config=config, channel="testchannel")

        msg = ChatMessage(author="user1", text="bom dia chat", timestamp=datetime.now(timezone.utc))
        event = detector.process_message(msg)
        self.assertIsNone(event)

    def test_hype_detector_burst_triggers_event(self):
        config = HypeRuleConfig(
            window_seconds=5,
            threshold_mps=2.0,
            min_score=5.0,
            cooldown_seconds=30,
            keywords=["POG", "CLIP"],
        )
        detector = SlidingWindowHypeDetector(config=config, channel="testchannel")

        event = None
        now = datetime.now(timezone.utc)
        for i in range(10):
            msg = ChatMessage(
                author=f"user_{i}",
                text="POG POG CLIP IT NOW",
                timestamp=now,
                is_subscriber=True,
                bits=50,
            )
            res = detector.process_message(msg)
            if res:
                event = res
                break

        self.assertIsNotNone(event)
        self.assertIsInstance(event, HypeEvent)
        self.assertGreaterEqual(event.score, 5.0)
        self.assertEqual(event.streamer_channel, "testchannel")
        self.assertIsNotNone(event.breakdown)
        self.assertGreater(event.breakdown.keyword_matches, 0)


if __name__ == "__main__":
    unittest.main()
