"""
Standalone CLI runner for video_processor module.
Allows testing video generation and vertical crop without chat listener.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import get_settings
from core.models import HypeEvent
from modules.video_processor.ffmpeg_processor import FFmpegVideoProcessor
from modules.video_processor.mock_processor import MockVideoProcessor
from modules.video_processor.stream_buffer import StreamBufferManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("video_processor.cli")


async def generate_synthetic_test_video(output_path: Path, duration: int = 60) -> Path:
    """Gera um vídeo local sintético 16:9 (1280x720) para testes de segmentação e recorte."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "/usr/bin/ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=1000:duration={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    return output_path


async def run_processor(mode: str, framing: str) -> None:
    settings = get_settings()

    if mode == "mock":
        processor = MockVideoProcessor(
            output_dir=settings.storage_dir,
            vertical_aspect=True,
            ffmpeg_path=settings.ffmpeg_path,
        )
        fake_hype = HypeEvent(
            event_name="Clipe Detectado",
            score=9.5,
            reason="Teste isolado modo mock",
            streamer_channel=settings.twitch_channel,
            suggested_duration=10.0,
        )
        clip = await processor.create_clip(fake_hype)
    else:
        # Modo Buffer com segmentação real e corte de 30s pré + 15s pós
        buffer_mgr = StreamBufferManager(
            buffer_dir=settings.stream_buffer_dir,
            max_buffer_seconds=120.0,
            segment_duration=2.0,
            ffmpeg_path=settings.ffmpeg_path,
        )

        # 1. Cria vídeo local de 60 segundos
        local_src = settings.storage_dir / "sample_source_60s.mp4"
        logger.info(f"Gerando vídeo fonte local de 60s em {local_src}...")
        await generate_synthetic_test_video(local_src, duration=60)

        # 2. Alimenta o buffer com segmentos .ts
        from datetime import datetime, timezone, timedelta
        base_time = datetime.now(timezone.utc)
        await buffer_mgr.feed_local_video(local_src, base_timestamp=base_time)

        # 3. Simula evento de 'Clipe Detectado' com pico aos 35s do vídeo
        peak_time = base_time + timedelta(seconds=35.0)
        fake_hype = HypeEvent(
            event_name="Clipe Detectado",
            score=15.0,
            reason="Pico detectado aos 35s do vídeo (corte: 5s a 50s)",
            streamer_channel=settings.twitch_channel,
            timestamp=peak_time,
            suggested_duration=45.0,
            pre_roll_seconds=30.0,
        )

        processor = FFmpegVideoProcessor(
            output_dir=settings.storage_dir,
            buffer_manager=buffer_mgr,
            framing_mode=framing,
            preroll_seconds=30.0,
            postroll_seconds=15.0,
            ffmpeg_path=settings.ffmpeg_path,
        )

        print("\n" + "=" * 65)
        print(f" Testando FFmpeg Video Processor (Buffer 2 min em .ts)")
        print(f" Enquadramento: {framing.upper()} (9:16 - 1080x1920)")
        print(f" Pico de Hype:  {peak_time.isoformat()}")
        print(f" Intervalo:     30s antes até 15s depois (45s total)")
        print("=" * 65 + "\n")

        clip = await processor.create_clip(fake_hype)

    print("\n" + "=" * 65)
    print(" [CLIPE GERADO COM SUCESSO]")
    print(f" ID:          {clip.clip_id}")
    print(f" Arquivo:     {clip.file_path}")
    print(f" Resolução:   {clip.resolution[0]}x{clip.resolution[1]}")
    print(f" Duração:     {clip.duration}s")
    print(f" Título:      {clip.title}")
    print(f" Arquivo OK?: {clip.file_exists()}")
    print("=" * 65 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste isolado do Video Processor")
    parser.add_argument("--mode", choices=["buffer", "mock"], default="buffer", help="Modo de execução")
    parser.add_argument("--framing", choices=["blur", "crop"], default="blur", help="Modo de enquadramento 9:16")
    args = parser.parse_args()

    asyncio.run(run_processor(args.mode, args.framing))


if __name__ == "__main__":
    main()
