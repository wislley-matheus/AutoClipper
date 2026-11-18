"""
Tests for video_processor module.
Validates stream buffer management, segment stitching (30s before + 15s after peak),
and FFmpeg 9:16 vertical video conversion with blurred background using local .mp4.
"""
import asyncio
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from core.models import HypeEvent, ClipMetadata
from modules.video_processor.ffmpeg_processor import FFmpegVideoProcessor
from modules.video_processor.mock_processor import MockVideoProcessor
from modules.video_processor.stream_buffer import StreamBufferManager


def create_local_test_mp4(file_path: Path, duration: int = 50) -> Path:
    """Cria um vídeo .mp4 local real usando padrão de teste do FFmpeg."""
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
        str(file_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"Falha ao gerar MP4 local para teste: {res.stderr.decode()}")
    return file_path


def probe_video(file_path: Path) -> dict:
    """Extrai informações de resolução e duração usando ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-of", "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Falha ao executar ffprobe: {res.stderr}")
    data = json.loads(res.stdout)
    return data["streams"][0]


class TestVideoProcessor(unittest.IsolatedAsyncioTestCase):

    async def test_ffmpeg_processor_stitches_and_crops_local_mp4(self):
        """
        Teste unitário principal:
        1. Cria um vídeo local .mp4 de 55 segundos.
        2. Alimenta o StreamBufferManager que gera fatias .ts de 2 segundos.
        3. Simula evento de 'Clipe Detectado' com pico aos 32 segundos.
        4. O FFmpegVideoProcessor junta os segmentos de 30s antes (2s) a 15s depois (47s) -> 45s total.
        5. Aplica o filtro de fundo desfocado (9:16 vertical - 1080x1920) e salva o MP4.
        6. Valida dimensões (1080x1920) e duração (~45s) com ffprobe.
        """
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            buffer_dir = tmp_dir / "buffer"
            output_dir = tmp_dir / "clips"
            local_mp4 = tmp_dir / "local_test_video.mp4"

            # 1. Gera vídeo fonte local de 55s
            create_local_test_mp4(local_mp4, duration=55)
            self.assertTrue(local_mp4.exists())

            # 2. Inicializa o Buffer Manager e alimenta com o vídeo local
            buffer_mgr = StreamBufferManager(
                buffer_dir=buffer_dir,
                max_buffer_seconds=120.0,
                segment_duration=2.0,
            )
            base_time = datetime.now(timezone.utc)
            segments = await buffer_mgr.feed_local_video(local_mp4, base_timestamp=base_time)

            self.assertGreaterEqual(len(segments), 25)
            self.assertTrue(all(s.exists for s in segments))

            # 3. Simula evento 'Clipe Detectado' com pico aos 32s
            peak_time = base_time + timedelta(seconds=32.0)
            hype_event = HypeEvent(
                event_name="Clipe Detectado",
                score=12.5,
                reason="Pico 12.5x aos 32s do vídeo local",
                streamer_channel="streamer_teste",
                timestamp=peak_time,
                suggested_duration=45.0,
                pre_roll_seconds=30.0,
            )

            # 4. Executa o FFmpegVideoProcessor com fundo desfocado
            processor = FFmpegVideoProcessor(
                output_dir=output_dir,
                buffer_manager=buffer_mgr,
                framing_mode="blur",
                preroll_seconds=30.0,
                postroll_seconds=15.0,
            )

            clip = await processor.create_clip(hype_event)

            # 5. Validação das propriedades do ClipMetadata
            self.assertIsInstance(clip, ClipMetadata)
            self.assertEqual(clip.resolution, (1080, 1920))
            self.assertTrue(clip.file_exists())
            self.assertIn("streamer_teste", clip.tags)

            # 6. Validação técnica via ffprobe no arquivo MP4 gerado
            probe_data = probe_video(Path(clip.file_path))
            width = int(probe_data["width"])
            height = int(probe_data["height"])
            duration = float(probe_data["duration"])

            # Proporção 9:16 vertical exata
            self.assertEqual(width, 1080)
            self.assertEqual(height, 1920)

            # Duração esperada de ~45s (30s antes + 15s depois)
            self.assertAlmostEqual(duration, 45.0, delta=2.5)

    async def test_ffmpeg_processor_center_crop_mode(self):
        """Valida que o modo 'crop' (enquadramento centralizado) também produz 1080x1920."""
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            buffer_dir = tmp_dir / "buffer"
            output_dir = tmp_dir / "clips"
            local_mp4 = tmp_dir / "short_test.mp4"

            # Gera vídeo curto de 15s
            create_local_test_mp4(local_mp4, duration=15)

            buffer_mgr = StreamBufferManager(
                buffer_dir=buffer_dir,
                max_buffer_seconds=120.0,
                segment_duration=2.0,
            )
            base_time = datetime.now(timezone.utc)
            await buffer_mgr.feed_local_video(local_mp4, base_timestamp=base_time)

            peak_time = base_time + timedelta(seconds=8.0)
            hype_event = HypeEvent(
                event_name="Clipe Detectado",
                score=5.0,
                reason="Pico curto de teste",
                streamer_channel="crop_teste",
                timestamp=peak_time,
                suggested_duration=10.0,
                pre_roll_seconds=5.0,
            )

            processor = FFmpegVideoProcessor(
                output_dir=output_dir,
                buffer_manager=buffer_mgr,
                framing_mode="crop",
                preroll_seconds=5.0,
                postroll_seconds=5.0,
            )

            clip = await processor.create_clip(hype_event)
            probe_data = probe_video(Path(clip.file_path))

            self.assertEqual(int(probe_data["width"]), 1080)
            self.assertEqual(int(probe_data["height"]), 1920)

    async def test_mock_video_processor_generates_clip(self):
        """Valida funcionamento rápido do processador mock de fallback."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            processor = MockVideoProcessor(
                output_dir=tmp_dir,
                vertical_aspect=True,
            )

            hype = HypeEvent(
                score=10.0,
                reason="Teste unitario de video mock",
                streamer_channel="teststreamer",
                suggested_duration=2.0,
            )

            clip = await processor.create_clip(hype)

            self.assertIsInstance(clip, ClipMetadata)
            self.assertEqual(clip.resolution, (1080, 1920))
            self.assertTrue(Path(clip.file_path).exists())
            self.assertGreater(Path(clip.file_path).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
