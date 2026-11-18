"""
FFmpeg Video Processor implementation.
Stitches rolling .ts stream buffer segments (30s before + 15s after peak),
applies 9:16 vertical crop (1080x1920) with blurred background or center crop,
and outputs a ready-to-publish MP4 video.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from core.models import ClipMetadata, HypeEvent
from .base import BaseVideoProcessor
from .stream_buffer import StreamBufferManager

logger = logging.getLogger("twitch_auto_clipper.ffmpeg_processor")


class FFmpegVideoProcessor(BaseVideoProcessor):
    """
    Processador de vídeo que utiliza FFmpeg para concatenar segmentos .ts do buffer
    e converter o vídeo para o formato vertical 9:16 (1080x1920) com fundo desfocado.
    """

    def __init__(
        self,
        output_dir: Path | str = "./storage/clips",
        buffer_manager: Optional[StreamBufferManager] = None,
        framing_mode: str = "blur",  # 'blur' (fundo desfocado) ou 'crop' (enquadramento centralizado)
        preroll_seconds: float = 30.0,
        postroll_seconds: float = 15.0,
        ffmpeg_path: str = "/usr/bin/ffmpeg",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.buffer_manager = buffer_manager or StreamBufferManager(ffmpeg_path=ffmpeg_path)
        self.framing_mode = framing_mode.lower()
        self.preroll_seconds = preroll_seconds
        self.postroll_seconds = postroll_seconds
        self.ffmpeg_path = ffmpeg_path

    def build_filter_graph(self) -> str:
        """
        Retorna o grafo de filtros FFmpeg para o formato 9:16 (1080x1920).
        Suporta 'blur' (fundo desfocado) e 'crop' (corte centralizado).
        """
        if self.framing_mode == "crop":
            # Enquadramento centralizado 9:16 direto
            return "[0:v]crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920[outv]"

        # Padrão: Fundo desfocado (Blurred Background)
        # 1. in_bg: reduz escala, desfoca com boxblur e reescala para 1080x1920
        # 2. in_fg: escala proporcional sem cortes
        # 3. overlay: sobrepõe o vídeo centralizado no fundo desfocado
        return (
            "[0:v]split=2[in_fg][in_bg];"
            "[in_bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:10,scale=1080:1920[bg];"
            "[in_fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
        )

    async def render_from_segments(
        self,
        segment_paths: List[Path],
        seek_offset: float,
        duration: float,
        output_file: Path,
    ) -> Path:
        """
        Concatena uma lista de arquivos .ts usando o concat demuxer do FFmpeg,
        aplica o recorte vertical e salva o MP4 final.
        """
        if not segment_paths:
            raise ValueError("Nenhum segmento fornecido para renderização.")

        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Cria arquivo de manifesto para concat demuxer
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for p in segment_paths:
                f.write(f"file '{p.resolve()}'\n")
            concat_manifest = Path(f.name)

        try:
            filter_graph = self.build_filter_graph()
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-ss", f"{seek_offset:.3f}",
                "-t", f"{duration:.3f}",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_manifest),
                "-filter_complex", filter_graph,
                "-map", "[outv]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_file),
            ]

            logger.info(f"Executando renderização FFmpeg 9:16 ({len(segment_paths)} segmentos, {duration:.1f}s)...")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                err_text = stderr.decode(errors="ignore")[-400:]
                raise RuntimeError(f"FFmpeg falhou na renderização: {err_text}")

            if not output_file.exists() or output_file.stat().st_size == 0:
                raise RuntimeError(f"Arquivo de saída não foi gerado ou está vazio: {output_file}")

            logger.info(f"Clipe vertical 9:16 gerado com sucesso: {output_file}")
            return output_file
        finally:
            try:
                concat_manifest.unlink()
            except Exception:
                pass

    async def create_clip(self, hype_event: HypeEvent) -> ClipMetadata:
        """
        Processa o evento 'Clipe Detectado':
        - Determina o momento do pico
        - Seleciona segmentos de 30s antes a 15s depois
        - Executa concatenação e conversão 9:16 com fundo desfocado
        """
        peak_ts = hype_event.timestamp.timestamp()
        start_ts = peak_ts - self.preroll_seconds
        end_ts = peak_ts + self.postroll_seconds
        target_duration = self.preroll_seconds + self.postroll_seconds  # 45.0s

        clip_id = f"clip_{hype_event.event_id}_{int(peak_ts)}"
        target_path = self.output_dir / f"{clip_id}.mp4"

        logger.info(
            f"Processando evento '{hype_event.event_name}': janela de {self.preroll_seconds}s antes "
            f"e {self.postroll_seconds}s depois do pico ({target_duration:.1f}s total)."
        )

        segments, seek_offset, duration = self.buffer_manager.get_segments_for_range(start_ts, end_ts)

        if not segments:
            logger.warning("Segmentos não encontrados no buffer de stream. Utilizando gerador sintético de fallback.")
            from .mock_processor import MockVideoProcessor
            fallback = MockVideoProcessor(self.output_dir, vertical_aspect=True, ffmpeg_path=self.ffmpeg_path)
            return await fallback.create_clip(hype_event)

        # Renderiza os segmentos
        final_file = await self.render_from_segments(
            segment_paths=segments,
            seek_offset=seek_offset,
            duration=duration or target_duration,
            output_file=target_path,
        )

        title = f"MOMENTO ÉPICO! {hype_event.streamer_channel.upper()} #Shorts"
        description = (
            f"Momento de Hype capturado automaticamente!\n"
            f"Pico: {hype_event.reason}\n"
            f"Timestamp: {hype_event.timestamp.isoformat()}\n\n"
            f"#twitch #clips #shorts #gaming #tiktok"
        )
        tags = ["twitch", "shorts", hype_event.streamer_channel, "gaming", "clips"]

        return ClipMetadata(
            clip_id=clip_id,
            file_path=str(final_file.resolve()),
            title=title,
            description=description,
            tags=tags,
            duration=duration or target_duration,
            resolution=(1080, 1920),
            created_at=datetime.now(timezone.utc),
            hype_score=hype_event.score,
        )
