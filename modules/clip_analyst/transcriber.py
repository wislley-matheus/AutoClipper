"""
Transcrição de áudio via faster-whisper.

Extrai o áudio do vídeo com FFmpeg e executa o modelo Whisper localmente.
Funciona em modo CPU (compute_type="int8") sem GPU.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AudioTranscriber:
    """Transcreve o áudio de um arquivo de vídeo usando faster-whisper."""

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "pt",
        ffmpeg_path: str = "/usr/bin/ffmpeg",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.ffmpeg_path = ffmpeg_path
        self._model = None  # carregado sob demanda

    def _load_model(self):
        """Carrega o modelo Whisper (lazy loading para economizar memória)."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                logger.info(
                    "Carregando modelo Whisper '%s' (device=%s, compute_type=%s)...",
                    self.model_size,
                    self.device,
                    self.compute_type,
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                logger.info("Modelo Whisper carregado com sucesso.")
            except ImportError:
                logger.error("faster-whisper não instalado. Transcrição desativada.")
                self._model = None
        return self._model

    def _extract_audio_wav(self, video_path: str, output_wav: str) -> bool:
        """Extrai o áudio do vídeo como WAV mono 16kHz (formato ideal para Whisper)."""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            output_wav,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning("FFmpeg retornou erro ao extrair áudio: %s", result.stderr[-500:])
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("Falha ao executar FFmpeg para extração de áudio: %s", exc)
            return False

    def transcribe(self, video_path: str) -> str:
        """
        Transcreve o áudio do vídeo e retorna o texto completo.

        Args:
            video_path: Caminho para o arquivo de vídeo (.mp4, .ts, etc.)

        Returns:
            Texto transcrito ou "[Transcrição indisponível]" em caso de falha.
        """
        model = self._load_model()
        if model is None:
            return "[Transcrição indisponível: modelo não carregado]"

        video_file = Path(video_path)
        if not video_file.exists():
            logger.warning("Arquivo de vídeo não encontrado: %s", video_path)
            return "[Transcrição indisponível: arquivo não encontrado]"

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = tmp.name

            logger.info("Extraindo áudio de '%s'...", video_file.name)
            audio_ok = self._extract_audio_wav(video_path, tmp_wav)

            if not audio_ok:
                return "[Transcrição indisponível: falha na extração de áudio]"

            logger.info("Transcrevendo com Whisper (idioma=%s)...", self.language)
            segments, info = model.transcribe(
                tmp_wav,
                language=self.language,
                beam_size=1,  # mais rápido
                vad_filter=True,  # filtra silêncio
            )

            texto = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(
                "Transcrição concluída: %.1fs de áudio, %d chars detectados.",
                info.duration,
                len(texto),
            )
            return texto if texto else "[Sem fala detectada]"

        except Exception as exc:
            logger.exception("Erro inesperado na transcrição: %s", exc)
            return "[Transcrição indisponível: erro interno]"
        finally:
            # limpa WAV temporário
            try:
                Path(tmp_wav).unlink(missing_ok=True)
            except Exception:
                pass
