"""Tests for MovingAverageHypeDetector."""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from core.models import ChatMessage, HypeEvent
from modules.hype_detector.moving_average_detector import MovingAverageHypeDetector


class TestMovingAverageHypeDetector(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.events_dir = Path(self.tmp_dir.name)
        self.detector = MovingAverageHypeDetector(
            channel="testchannel",
            interval_seconds=5.0,
            spike_multiplier=3.0,
            history_window_intervals=6,
            min_baseline=2.0,
            min_spike_messages=3,
            cooldown_seconds=10.0,
            events_dir=self.events_dir,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_normal_chat_no_spike(self):
        """Testa tráfego estável com 2 mensagens a cada 5 segundos (não deve disparar)."""
        base_time = datetime.now(timezone.utc)

        # 3 intervalos normais de 5s com 2 mensagens cada
        for interval in range(3):
            interval_time = base_time + timedelta(seconds=interval * 5.0)
            for m in range(2):
                msg = ChatMessage(
                    author=f"user_{m}",
                    text=f"mensagem normal {m}",
                    timestamp=interval_time + timedelta(seconds=m),
                )
                event = self.detector.process_message(msg)
                self.assertIsNone(event)

            # Avalia fim do intervalo de 5s
            event = self.detector.evaluate_interval(interval_time + timedelta(seconds=4.9))
            self.assertIsNone(event)

    def test_spike_triggers_clip_detected_and_saves_json(self):
        """Testa pico superior a 3x a média normal, salvamento das mensagens em JSON e evento com timestamp exato."""
        base_time = datetime.now(timezone.utc)

        # 1. Alimenta baseline normal: 2 mensagens por intervalo de 5s (média móvel = 2.0)
        t1 = base_time
        for i in range(2):
            self.detector.process_message(ChatMessage(author=f"user_{i}", text=f"msg {i}", timestamp=t1))
        self.detector.evaluate_interval(t1 + timedelta(seconds=5.0))

        t2 = base_time + timedelta(seconds=5.0)
        for i in range(2):
            self.detector.process_message(ChatMessage(author=f"user_{i}", text=f"msg {i}", timestamp=t2))
        self.detector.evaluate_interval(t2 + timedelta(seconds=5.0))

        # A média normal até agora é 2.0 msgs/5s
        self.assertAlmostEqual(self.detector.normal_moving_average, 2.0, delta=0.1)

        # 2. Gera mais de 40 mensagens para verificar que o buffer retém exatamente as últimas 40
        t3 = base_time + timedelta(seconds=10.0)
        for i in range(45):
            self.detector.process_message(
                ChatMessage(
                    author=f"spammer_{i}",
                    text=f"POGGERS CLIP IT {i}",
                    timestamp=t3 + timedelta(milliseconds=i * 50),
                    bits=100 if i % 5 == 0 else 0,
                    is_subscriber=True,
                )
            )

        # No intervalo t3, foram enviadas 45 mensagens! 45 / 2.0 = 22.5x (> 3.0x)
        exact_eval_time = t3 + timedelta(seconds=5.0)
        event = self.detector.evaluate_interval(exact_eval_time)

        # 3. Validações do evento
        self.assertIsNotNone(event)
        self.assertIsInstance(event, HypeEvent)
        self.assertEqual(event.event_name, "Clipe Detectado")
        self.assertEqual(event.timestamp, exact_eval_time)
        self.assertGreaterEqual(event.score, 3.0)
        self.assertEqual(event.streamer_channel, "testchannel")
        self.assertIsNotNone(event.json_path)

        # 4. Validações do arquivo JSON gerado
        json_file = Path(event.json_path)
        self.assertTrue(json_file.exists())

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["event"], "Clipe Detectado")
        self.assertEqual(data["timestamp"], exact_eval_time.isoformat())
        self.assertEqual(data["channel"], "testchannel")
        self.assertGreaterEqual(data["metrics"]["spike_ratio"], 3.0)

        # Verifica que salvou exatamente as últimas 40 mensagens
        self.assertEqual(data["total_messages_saved"], 40)
        self.assertEqual(len(data["messages"]), 40)

        # Verifica conteúdo da última mensagem
        last_msg = data["messages"][-1]
        self.assertIn("spammer_44", last_msg["author"])


if __name__ == "__main__":
    unittest.main()
