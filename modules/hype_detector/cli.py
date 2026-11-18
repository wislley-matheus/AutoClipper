"""
Standalone CLI runner for hype_detector module.
Allows isolated testing with synthetic message bursts and customizable thresholds.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import get_settings
from modules.chat_listener.mock_listener import MockChatListener
from modules.hype_detector.detector import SlidingWindowHypeDetector
from modules.hype_detector.moving_average_detector import MovingAverageHypeDetector
from modules.hype_detector.rules import HypeRuleConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hype_detector.cli")


async def run_detector(threshold_mps: float, min_score: float, mode: str = "moving_average") -> None:
    settings = get_settings()

    if mode == "moving_average":
        logger.info("Executando MovingAverageHypeDetector (5s interval, 3x spike threshold)")
        detector = MovingAverageHypeDetector(
            channel=settings.twitch_channel,
            interval_seconds=settings.hype_interval_seconds,
            spike_multiplier=settings.hype_spike_multiplier,
            events_dir=settings.events_dir,
            cooldown_seconds=10.0,
        )
    else:
        logger.info("Executando SlidingWindowHypeDetector")
        config = HypeRuleConfig(
            window_seconds=settings.hype_window_seconds,
            threshold_mps=threshold_mps or settings.hype_threshold_mps,
            min_score=min_score or settings.hype_min_score,
            cooldown_seconds=10,
            keywords=settings.hype_keywords,
        )
        detector = SlidingWindowHypeDetector(
            config=config,
            channel=settings.twitch_channel,
            clip_duration=settings.clip_duration_seconds,
            clip_preroll=settings.clip_preroll_seconds,
        )

    listener = MockChatListener(
        channel=settings.twitch_channel,
        msg_interval=0.25,
        simulate_hype_after=4,
        hype_burst_count=18,
    )

    await listener.start()
    print("\n" + "=" * 65)
    print(f" Testando Hype Detector (Modo: {mode.upper()})")
    print(f" Canal: #{settings.twitch_channel}")
    print(f" Eventos salvos em: {settings.events_dir}")
    print(" Aguardando mensagens e simulando rajada de hype...")
    print("=" * 65 + "\n")

    events_detected = 0
    try:
        async for msg in listener.stream():
            event = detector.process_message(msg)
            print(f"[{msg.timestamp.strftime('%H:%M:%S')}] {msg.author}: {msg.text[:40]}")

            if event:
                events_detected += 1
                print("\n" + "!" * 65)
                print(f" [DISPARO DE EVENTO]: {event.event_name}")
                print(f" Timestamp Exato:    {event.timestamp.isoformat()}")
                print(f" Score / Multiplier: {event.score}x")
                print(f" Razão:              {event.reason}")
                if event.json_path:
                    print(f" JSON 40 mensagens:  {event.json_path}")
                print("!" * 65 + "\n")
                break
    except KeyboardInterrupt:
        pass
    finally:
        await listener.stop()
        logger.info(f"Fim do teste. Eventos detectados: {events_detected}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste isolado do Hype Detector")
    parser.add_argument("--mode", choices=["moving_average", "sliding_window"], default="moving_average", help="Algoritmo de detecção")
    parser.add_argument("--mps", type=float, default=3.0, help="Limiar de mensagens por segundo")
    parser.add_argument("--score", type=float, default=8.0, help="Score mínimo para disparo")
    args = parser.parse_args()

    asyncio.run(run_detector(args.mps, args.score, args.mode))


if __name__ == "__main__":
    main()
