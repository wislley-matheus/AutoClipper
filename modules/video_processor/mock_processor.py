"""
Mock Video Processor.
Creates synthetic video clips (using real FFmpeg if installed, or fallback mock container)
formatted as 9:16 vertical video suitable for YouTube Shorts and TikTok.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple
from core.models import ClipMetadata, HypeEvent
from .base import BaseVideoProcessor

logger = logging.getLogger("twitch_auto_clipper.mock_video_processor")


class MockVideoProcessor(BaseVideoProcessor):
    """Processador de vídeo mock para testes rápidos e desenvolvimento sem VOD real."""

    def __init__(
        self,
        output_dir: Path | str = "./storage/clips",
        vertical_aspect: bool = True,
        ffmpeg_path: str = "/usr/bin/ffmpeg",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.vertical_aspect = vertical_aspect
        self.ffmpeg_path = ffmpeg_path

    async def create_clip(self, hype_event: HypeEvent) -> ClipMetadata:
        """Gera um clipe de teste sintético com as dimensões e duração especificadas."""
        clip_id = f"clip_{hype_event.event_id}_{int(datetime.now(timezone.utc).timestamp())}"
        target_path = self.output_dir / f"{clip_id}.mp4"

        resolution: Tuple[int, int] = (1080, 1920) if self.vertical_aspect else (1920, 1080)
        duration = min(hype_event.suggested_duration, 5.0)  # 5s no mock para geração instantânea

        logger.info(f"Gerando clipe sintético {clip_id} ({resolution[0]}x{resolution[1]}, {duration}s)...")

        # Tenta gerar arquivo de vídeo real via ffmpeg se disponível
        has_ffmpeg = bool(shutil.which(self.ffmpeg_path) or shutil.which("ffmpeg"))
        success = False

        if has_ffmpeg:
            binary = self.ffmpeg_path if shutil.which(self.ffmpeg_path) else "ffmpeg"
            # Cria vídeo de teste colorido lavfi testsrc com áudio sintético
            cmd = [
                binary,
                "-y",
                "-f", "lavfi",
                "-i", f"testsrc=duration={duration}:size={resolution[0]}x{resolution[1]}:rate=30",
                "-f", "lavfi",
                "-i", f"sine=frequency=1000:duration={duration}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                str(target_path),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0 and target_path.exists():
                    success = True
                    logger.info(f"Clipe MP4 real gerado com sucesso via FFmpeg: {target_path}")
            except Exception as e:
                logger.warning(f"Falha ao executar FFmpeg: {e}. Criando arquivo mock binário.")

        if not success:
            # Fallback caso ffmpeg falhe
            with open(target_path, "wb") as f:
                f.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free")
                f.write(os.urandom(1024 * 100))  # 100KB mock payload
            logger.info(f"Arquivo mock criado: {target_path}")

        title = f"MOMENTO INSANO! {hype_event.streamer_channel.upper()} NO CSGO #Shorts"
        description = (
            f"Momento épico capturado automaticamente na live do {hype_event.streamer_channel}!\n"
            f"Score de Hype: {hype_event.score}/10\n"
            f"Gatilho: {hype_event.reason}\n\n"
            f"#twitch #clips #gaming #shorts #tiktok"
        )
        tags = ["twitch", "clips", hype_event.streamer_channel, "shorts", "gaming", "csgo"]

        return ClipMetadata(
            clip_id=clip_id,
            file_path=str(target_path.resolve()),
            title=title,
            description=description,
            tags=tags,
            duration=duration,
            resolution=resolution,
            created_at=datetime.now(timezone.utc),
            hype_score=hype_event.score,
        )
