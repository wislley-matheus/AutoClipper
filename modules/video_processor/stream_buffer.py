"""
Continuous Stream Buffer Manager using Streamlink and FFmpeg.
Maintains a rolling buffer of the last 2 minutes (120s) of stream video in .ts segments.
Supports both live Twitch stream capture and local video feeding for testing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("twitch_auto_clipper.stream_buffer")

try:
    import streamlink
    HAS_STREAMLINK = True
except ImportError:
    streamlink = None  # type: ignore
    HAS_STREAMLINK = False


@dataclass
class StreamSegment:
    """Metadados de um segmento .ts armazenado no buffer."""
    path: Path
    start_time: float  # Timestamp Unix (segundos com casas decimais)
    duration: float
    end_time: float

    @property
    def exists(self) -> bool:
        return self.path.is_file()


class StreamBufferManager:
    """
    Gerenciador de buffer contínuo em anel (rolling ring buffer).
    Mantém os últimos 2 minutos (120s) de vídeo em arquivos .ts.
    """

    def __init__(
        self,
        buffer_dir: Path | str = "./storage/buffer",
        max_buffer_seconds: float = 120.0,
        segment_duration: float = 2.0,
        ffmpeg_path: str = "/usr/bin/ffmpeg",
    ) -> None:
        self.buffer_dir = Path(buffer_dir)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self.max_buffer_seconds = max_buffer_seconds
        self.segment_duration = segment_duration
        self.ffmpeg_path = ffmpeg_path

        self._segments: List[StreamSegment] = []
        self._record_proc: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    @property
    def active_segments(self) -> List[StreamSegment]:
        """Retorna lista dos segmentos atualmente no buffer."""
        return [s for s in self._segments if s.exists]

    def clear(self) -> None:
        """Limpa arquivos do diretório de buffer e lista interna."""
        self._segments.clear()
        if self.buffer_dir.exists():
            for f in self.buffer_dir.glob("*.ts"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in self.buffer_dir.glob("*.txt"):
                try:
                    f.unlink()
                except Exception:
                    pass

    async def feed_local_video(
        self,
        local_video_path: Path | str,
        base_timestamp: Optional[datetime] = None,
    ) -> List[StreamSegment]:
        """
        Segmenta um vídeo local .mp4 em arquivos .ts de 2 segundos,
        preenchendo o buffer para testes e validação offline.
        """
        video_file = Path(local_video_path)
        if not video_file.is_file():
            raise FileNotFoundError(f"Vídeo de origem não encontrado: {video_file}")

        self.clear()
        base_ts = (base_timestamp or datetime.now(timezone.utc)).timestamp()
        output_pattern = str(self.buffer_dir / "seg_%04d.ts")

        # Segmenta o vídeo em fatias .ts com timestamps consistentes
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(video_file),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-f", "segment",
            "-segment_time", str(self.segment_duration),
            "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_duration})",
            "-reset_timestamps", "0",
            output_pattern,
        ]

        logger.info(f"Segmentando vídeo local {video_file.name} em pedaços de {self.segment_duration}s...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[-300:]
            raise RuntimeError(f"Falha ao segmentar vídeo local: {err}")

        # Indexa os segmentos gerados
        generated = sorted(self.buffer_dir.glob("seg_*.ts"))
        current_time = base_ts
        self._segments.clear()

        for seg_file in generated:
            seg = StreamSegment(
                path=seg_file.resolve(),
                start_time=current_time,
                duration=self.segment_duration,
                end_time=current_time + self.segment_duration,
            )
            self._segments.append(seg)
            current_time += self.segment_duration

        logger.info(f"Buffer carregado com {len(self._segments)} segmentos locais ({current_time - base_ts:.1f}s total).")
        return list(self._segments)

    def resolve_stream_url(self, channel: str, quality: str = "best") -> str:
        """Resolve a URL HLS da stream ao vivo da Twitch usando Streamlink."""
        if not HAS_STREAMLINK:
            raise RuntimeError("Biblioteca 'streamlink' não instalada. Execute 'pip install streamlink'.")

        session = streamlink.Streamlink()
        session.set_plugin_option("twitch", "twitch-disable-ads", True)
        session.set_plugin_option("twitch", "twitch-low-latency", True)

        clean_channel = channel.lower().replace("#", "")
        stream_target = f"https://www.twitch.tv/{clean_channel}"

        logger.info(f"Resolvendo stream da Twitch com Streamlink para {stream_target}...")
        streams = session.streams(stream_target)
        if not streams:
            raise RuntimeError(f"Canal #{clean_channel} está offline ou nenhuma stream foi detectada.")

        if quality in streams:
            stream_obj = streams[quality]
        else:
            stream_obj = list(streams.values())[0]

        return stream_obj.to_url()

    async def start_stream_recording(self, channel: str, quality: str = "best") -> None:
        """
        Inicia a gravação contínua da stream ao vivo via Streamlink e FFmpeg.
        Armazena segmentos .ts e limpa periodicamente os mais antigos que 2 minutos.
        """
        stream_url = self.resolve_stream_url(channel, quality)
        self._running = True

        output_pattern = str(self.buffer_dir / "live_seg_%05d.ts")
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", stream_url,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.segment_duration),
            "-segment_format", "mpegts",
            "-reset_timestamps", "0",
            output_pattern,
        ]

        logger.info(f"Iniciando gravação contínua do buffer de stream para #{channel}...")
        self._record_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Loop em background que limpa segmentos com mais de 2 minutos (120s)."""
        while self._running:
            await asyncio.sleep(5.0)
            now = time.time()
            cutoff = now - self.max_buffer_seconds

            # Atualiza lista de segmentos com base nos arquivos existentes
            files = sorted(self.buffer_dir.glob("live_seg_*.ts"))
            for f in files:
                mtime = f.stat().st_mtime
                if mtime < cutoff:
                    try:
                        f.unlink()
                        logger.debug(f"Segmento antigo removido do buffer: {f.name}")
                    except Exception:
                        pass

    async def stop(self) -> None:
        """Encerra a gravação e limpa processos em segundo plano."""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if self._record_proc:
            try:
                self._record_proc.terminate()
                await self._record_proc.wait()
            except Exception:
                pass
        logger.info("Gravação de buffer de stream finalizada.")

    def get_segments_for_range(
        self,
        start_timestamp: float,
        end_timestamp: float,
    ) -> Tuple[List[Path], float, float]:
        """
        Localiza os segmentos .ts correspondentes ao intervalo [start_timestamp, end_timestamp].
        Retorna (lista_de_arquivos, seek_offset_no_primeiro_segmento, duracao_total).
        """
        if not self._segments:
            # Tenta descobrir segmentos pelo mtime dos arquivos .ts
            files = sorted(self.buffer_dir.glob("*.ts"))
            if not files:
                return [], 0.0, 0.0
            # Se não estavam indexados, monta com base em mtime
            first_mtime = files[0].stat().st_mtime
            current_t = first_mtime
            for f in files:
                seg = StreamSegment(
                    path=f.resolve(),
                    start_time=current_t,
                    duration=self.segment_duration,
                    end_time=current_t + self.segment_duration,
                )
                self._segments.append(seg)
                current_t += self.segment_duration

        selected: List[StreamSegment] = []
        for seg in self._segments:
            # Verifica se o segmento se sobrepõe com a janela desejada
            if seg.end_time > start_timestamp and seg.start_time < end_timestamp:
                if seg.exists:
                    selected.append(seg)

        if not selected:
            logger.warning(
                f"Nenhum segmento encontrado para o intervalo [{start_timestamp:.1f}, {end_timestamp:.1f}]. "
                f"Buffer atual cobre [{self._segments[0].start_time:.1f}, {self._segments[-1].end_time:.1f}]."
            )
            return [], 0.0, 0.0

        # Calcula o offset dentro do primeiro segmento selecionado
        first_seg = selected[0]
        seek_offset = max(0.0, start_timestamp - first_seg.start_time)
        target_duration = max(1.0, end_timestamp - start_timestamp)

        paths = [s.path for s in selected]
        logger.info(
            f"Selecionados {len(paths)} segmentos para o clipe "
            f"(início offset: {seek_offset:.2f}s, duração total: {target_duration:.2f}s)."
        )
        return paths, seek_offset, target_duration
