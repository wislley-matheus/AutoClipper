"""
Main entry point and orchestrator for twitch-auto-clipper.

Pipeline completo (5 etapas):
  1. chat_listener   → recebe mensagens do chat Twitch
  2. hype_detector   → detecta picos de engajamento (média móvel)
  3. clip_analyst    → Whisper transcreve áudio + Gemini avalia potencial viral (1-10)
  4. video_processor → corta e renderiza clipe vertical 9:16 (1080×1920)
  5. social_uploader → publica no YouTube Shorts e TikTok

Módulos comunicam-se apenas via DTOs (core/models.py) e EventBus.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

# Garante importação da raiz
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import get_settings, Settings
from core.event_bus import EventBus
from core.models import ChatMessage, ClipMetadata, HypeEvent, UploadResult
from modules.chat_listener import BaseChatListener, MockChatListener, TwitchIRCListener, TwitchIOListener
from modules.hype_detector import (
    BaseHypeDetector,
    HypeRuleConfig,
    SlidingWindowHypeDetector,
    MovingAverageHypeDetector,
)
from modules.video_processor import BaseVideoProcessor, FFmpegVideoProcessor, MockVideoProcessor
from modules.social_uploader import (
    BaseSocialUploader,
    MockSocialUploader,
    MultiPlatformUploader,
    YouTubeUploader,
    TikTokUploader,
)
from modules.clip_analyst import ClipAnalyst, ClipAnalysisResult, AudioTranscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("twitch_auto_clipper.main")


class TwitchAutoClipperOrchestrator:
    """Orquestrador desacoplado que conecta os 5 módulos via EventBus."""

    def __init__(self, settings: Settings, live_mode: bool = False) -> None:
        self.settings = settings
        self.live_mode = live_mode
        self.bus = EventBus()
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Instanciação modular desacoplada
        self.chat_listener: BaseChatListener = self._create_chat_listener()
        self.hype_detector: BaseHypeDetector = self._create_hype_detector()
        self.clip_analyst: ClipAnalyst = self._create_clip_analyst()
        self.transcriber: AudioTranscriber = self._create_transcriber()
        self.video_processor: BaseVideoProcessor = self._create_video_processor()
        self.social_uploader: MultiPlatformUploader = self._create_social_uploader()

    def _create_chat_listener(self) -> BaseChatListener:
        if self.live_mode and not self.settings.mock_mode:
            if self.settings.twitch_client_id and self.settings.twitch_client_id != "mock_twitch_client_id":
                logger.info(f"Modo LIVE ativado: Conectando com TwitchIO ao #{self.settings.twitch_channel}")
                return TwitchIOListener(
                    channel=self.settings.twitch_channel,
                    client_id=self.settings.twitch_client_id,
                    client_secret=self.settings.twitch_client_secret,
                    token=self.settings.twitch_oauth_token,
                )
            logger.info(f"Modo LIVE ativado: Conectando ao Twitch IRC #{self.settings.twitch_channel}")
            return TwitchIRCListener(
                channel=self.settings.twitch_channel,
                nickname=self.settings.twitch_bot_nickname,
                token=self.settings.twitch_oauth_token,
            )
        logger.info(f"Modo MOCK ativado: Simulando chat para #{self.settings.twitch_channel}")
        return MockChatListener(
            channel=self.settings.twitch_channel,
            msg_interval=0.25,
            simulate_hype_after=3,
            hype_burst_count=16,
        )

    def _create_hype_detector(self) -> BaseHypeDetector:
        logger.info(
            f"Configurando MovingAverageHypeDetector: intervalo={self.settings.hype_interval_seconds}s, "
            f"limiar={self.settings.hype_spike_multiplier}x média normal, events_dir={self.settings.events_dir}"
        )
        return MovingAverageHypeDetector(
            channel=self.settings.twitch_channel,
            interval_seconds=float(self.settings.hype_interval_seconds),
            spike_multiplier=self.settings.hype_spike_multiplier,
            events_dir=self.settings.events_dir,
            cooldown_seconds=15.0,
        )

    def _create_clip_analyst(self) -> ClipAnalyst:
        logger.info(
            "Configurando ClipAnalyst: modelo=%s, nota_mínima=%.1f",
            self.settings.gemini_model,
            self.settings.min_clip_score,
        )
        return ClipAnalyst(
            api_key=self.settings.gemini_api_key,
            model=self.settings.gemini_model,
            min_score=self.settings.min_clip_score,
            channel=self.settings.twitch_channel,
        )

    def _create_transcriber(self) -> AudioTranscriber:
        logger.info(
            "Configurando AudioTranscriber: modelo_whisper=%s, device=%s",
            self.settings.whisper_model_size,
            self.settings.whisper_device,
        )
        return AudioTranscriber(
            model_size=self.settings.whisper_model_size,
            device=self.settings.whisper_device,
            language=self.settings.whisper_language,
            ffmpeg_path=self.settings.ffmpeg_path,
        )

    def _create_video_processor(self) -> BaseVideoProcessor:
        if self.live_mode and not self.settings.mock_mode:
            return FFmpegVideoProcessor(
                output_dir=self.settings.storage_dir,
                vertical_aspect=self.settings.video_vertical_aspect,
                ffmpeg_path=self.settings.ffmpeg_path,
            )
        return MockVideoProcessor(
            output_dir=self.settings.storage_dir,
            vertical_aspect=self.settings.video_vertical_aspect,
            ffmpeg_path=self.settings.ffmpeg_path,
        )

    def _create_social_uploader(self) -> MultiPlatformUploader:
        multi = MultiPlatformUploader()
        if self.settings.youtube_enabled:
            if self.live_mode and not self.settings.mock_mode:
                secrets = Path(self.settings.youtube_client_secrets_file)
                if secrets.exists():
                    logger.info("YouTubeUploader REAL configurado (credenciais encontradas).")
                    multi.add_uploader(YouTubeUploader(
                        client_secrets_file=str(secrets),
                        token_file=self.settings.youtube_token_file,
                        privacy_status=self.settings.youtube_privacy_status,
                    ))
                else:
                    logger.warning("Credenciais YouTube ausentes — usando mock.")
                    multi.add_uploader(MockSocialUploader(platform="youtube"))
            else:
                multi.add_uploader(MockSocialUploader(platform="youtube"))

        if self.settings.tiktok_enabled:
            if self.live_mode and not self.settings.mock_mode:
                token = self.settings.tiktok_access_token
                if token and not token.startswith("mock_"):
                    logger.info("TikTokUploader REAL configurado (access_token presente).")
                    multi.add_uploader(TikTokUploader(
                        access_token=token,
                        privacy_level=self.settings.tiktok_privacy_level,
                    ))
                else:
                    logger.warning("TikTok access_token é mock — usando mock uploader.")
                    multi.add_uploader(MockSocialUploader(platform="tiktok"))
            else:
                multi.add_uploader(MockSocialUploader(platform="tiktok"))

        if self.settings.instagram_enabled:
            multi.add_uploader(MockSocialUploader(platform="instagram"))

        return multi

    async def _on_hype_detected(self, hype: HypeEvent) -> None:
        """
        Handler acionado quando um evento de hype é detectado.

        Pipeline de 3 etapas antes do render final:
          1. Transcrição do áudio (Whisper) — se já houver segmentos de buffer.
          2. Análise Gemini — nota 1-10, título viral, hashtags.
          3. Gate de qualidade — só renderiza se nota >= min_clip_score.
        """
        print("\n" + "🔥" * 35)
        print(f" [EVENTO]: {hype.event_name.upper()}!")
        print(f" Timestamp Exato: {hype.timestamp.isoformat()}")
        print(f" Razão:           {hype.reason}")
        print(f" Score / Pico:    {hype.score}x a média normal")
        if hype.json_path:
            print(f" JSON 40 msgs:    {hype.json_path}")
        print("🔥" * 35 + "\n")

        # ── Etapa 1: Transcrição de áudio ──────────────────────────────────
        # Verifica se há um clipe temporário no buffer para transcrever.
        # Em modo mock ou sem buffer, pula a transcrição silenciosamente.
        transcript = ""
        raw_clip_path: Optional[str] = None

        # Tenta encontrar um arquivo MP4 recente no diretório de clips
        clips_dir = self.settings.storage_dir
        mp4_files = sorted(clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4_files:
            raw_clip_path = str(mp4_files[0])
            logger.info("Transcrevendo áudio de '%s' para análise Gemini...", raw_clip_path)
            transcript = self.transcriber.transcribe(raw_clip_path)
            logger.info("Transcrição: %s...", transcript[:100] if transcript else "(vazio)")
        else:
            logger.info("Sem clipe no buffer para transcrever — análise sem áudio.")

        # ── Etapa 2: Análise Gemini ─────────────────────────────────────────
        print("\n" + "🤖" * 35)
        print(" [ANÁLISE GEMINI]: Avaliando potencial viral...")
        analysis: ClipAnalysisResult = await self.clip_analyst.analyze(
            hype_event=hype,
            transcript=transcript,
            video_path=raw_clip_path,
        )
        print(str(analysis))
        print("🤖" * 35 + "\n")

        # ── Etapa 3: Gate de qualidade ──────────────────────────────────────
        if not analysis.should_post:
            logger.info(
                "Clipe descartado (nota %.1f < mínimo %.1f): %s",
                analysis.score,
                self.settings.min_clip_score,
                analysis.reasoning,
            )
            print(f"\n⛔ Clipe descartado — nota {analysis.score:.1f}/10 abaixo do limiar "
                  f"{self.settings.min_clip_score:.1f}. Próximo pico...\n")
            return

        logger.info(
            "Clipe aprovado (nota %.1f) → iniciando renderização: '%s'",
            analysis.score,
            analysis.title,
        )

        # ── Etapa 4: Renderização do vídeo ──────────────────────────────────
        # Injeta título e hashtags gerados pelo Gemini nos metadados do clipe
        hype.reason = f"[Gemini {analysis.score:.0f}/10] {analysis.title}"
        clip = await self.video_processor.create_clip(hype)

        # Enriquece metadados do clipe com dados do Gemini
        clip.title = analysis.title
        clip.tags = analysis.hashtags
        clip.description = (
            f"{analysis.title}\n\n"
            f"{' '.join(analysis.hashtags)}\n\n"
            f"Detectado automaticamente pelo Twitch Auto Clipper."
        )
        clip.hype_score = analysis.score

        await self.bus.publish("clip.created", clip)

    async def _on_clip_created(self, clip: ClipMetadata) -> None:
        """Handler acionado quando um clipe é finalizado pelo processador de vídeo."""
        print("\n" + "🎬" * 35)
        print(f" [CLIPE GERADO]: {clip.title}")
        print(f" Arquivo: {clip.file_path} ({clip.duration}s)")
        print("🎬" * 35 + "\n")

        # Envio para redes sociais
        results = await self.social_uploader.upload_all(clip)
        print("\n" + "🚀" * 35)
        print(" [RESULTADOS DE PUBLICAÇÃO]:")
        for res in results:
            icon = "✅" if res.success else "❌"
            print(f" {icon} {res.platform.upper()}: {res.post_url or res.error_message}")
        print("🚀" * 35 + "\n")

    async def run(self, max_events: Optional[int] = None) -> None:
        """Inicia o pipeline integrado."""
        self._running = True
        logger.info("Iniciando Twitch Auto Clipper...")

        # Conecta eventos aos handlers
        self.bus.subscribe("hype.detected", self._on_hype_detected)
        self.bus.subscribe("clip.created", self._on_clip_created)

        # Inicia Chat Listener
        await self.chat_listener.start()

        events_processed = 0

        try:
            async for msg in self.chat_listener.stream():
                if not self._running:
                    break

                # Avalia mensagem com HypeDetector
                hype_event = self.hype_detector.process_message(msg)
                if hype_event:
                    events_processed += 1
                    await self.bus.publish("hype.detected", hype_event)

                    if max_events is not None and events_processed >= max_events:
                        logger.info(f"Meta de {max_events} evento(s) atingida. Encerrando pipeline.")
                        break

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Encerrando pipeline sob solicitação...")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Pára todos os serviços."""
        self._running = False
        await self.chat_listener.stop()
        logger.info("Twitch Auto Clipper encerrado com sucesso.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitch Auto Clipper - Pipeline Orquestrador")
    parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Executa uma demonstração de ponta a ponta (chat -> hype -> corte 9:16 -> upload) e encerra",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Executa em modo ao vivo (conecta ao chat real da Twitch)",
    )
    parser.add_argument(
        "--channel",
        type=str,
        default=None,
        help="Sobrescreve o canal da Twitch configurado no .env",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.channel:
        settings.twitch_channel = args.channel

    live_mode = args.live or not settings.mock_mode

    orchestrator = TwitchAutoClipperOrchestrator(settings=settings, live_mode=live_mode)

    print("=" * 70)
    print("   TWITCH AUTO CLIPPER - SISTEMA AUTOMATIZADO DE CORTES VIRAIS")
    print("=" * 70)
    print(f" Canal:       #{settings.twitch_channel}")
    print(f" Modo:        {'LIVE (Twitch IRC)' if live_mode else 'MOCK (Simulador)'}")
    print(f" Redes:       YouTube ({settings.youtube_enabled}) | TikTok ({settings.tiktok_enabled}) | IG ({settings.instagram_enabled})")
    print(f" Destino:     {settings.storage_dir}")
    print("=" * 70 + "\n")

    max_events = 1 if args.demo else None
    try:
        asyncio.run(orchestrator.run(max_events=max_events))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
