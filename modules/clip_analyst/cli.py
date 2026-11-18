"""
CLI standalone para o módulo clip_analyst.

Uso:
    python -m modules.clip_analyst.cli \\
        --json-path storage/events/clipe_detectado_123.json \\
        --video-path storage/clips/clip_123.mp4 \\
        --api-key SUA_CHAVE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisa um clipe via Gemini AI e gera título viral."
    )
    parser.add_argument("--json-path", required=False, help="Caminho para o JSON de mensagens do chat")
    parser.add_argument("--video-path", required=False, help="Caminho para o vídeo do clipe (.mp4)")
    parser.add_argument("--api-key", required=False, default="", help="Chave da API Gemini")
    parser.add_argument("--model", default="gemini-2.0-flash", help="Modelo Gemini a usar")
    parser.add_argument("--min-score", type=float, default=6.0, help="Nota mínima para postar")
    parser.add_argument("--channel", default="desconhecido", help="Nome do canal Twitch")
    parser.add_argument("--whisper-model", default="tiny", help="Tamanho do modelo Whisper")
    parser.add_argument("--no-transcribe", action="store_true", help="Pula transcrição de áudio")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # Importações locais (evita circular imports no topo)
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from core.models import HypeEvent
    from modules.clip_analyst.analyst import ClipAnalyst
    from modules.clip_analyst.transcriber import AudioTranscriber

    # Monta um HypeEvent mínimo para o CLI
    hype = HypeEvent(
        event_name="Clipe Detectado",
        score=10.0,
        reason="Disparo manual via CLI",
        timestamp=datetime.now(timezone.utc),
        json_path=args.json_path,
        spike_multiplier=3.5,
        recent_messages_count=25,
    )

    # 1. Transcrição
    transcript = ""
    if args.video_path and not args.no_transcribe:
        logger.info("Transcrevendo áudio de '%s'...", args.video_path)
        transcriber = AudioTranscriber(model_size=args.whisper_model)
        transcript = transcriber.transcribe(args.video_path)
        logger.info("Transcrição: %s", transcript[:200] + "..." if len(transcript) > 200 else transcript)
    else:
        logger.info("Transcrição de áudio pulada.")

    # 2. Análise Gemini
    api_key = args.api_key or os.getenv("GEMINI_API_KEY", "")
    analyst = ClipAnalyst(
        api_key=api_key,
        model=args.model,
        min_score=args.min_score,
        channel=args.channel,
    )

    result = await analyst.analyze(hype, transcript=transcript)

    # 3. Exibe resultado
    print("\n" + "=" * 60)
    print(str(result))
    print("=" * 60)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    sys.exit(0 if result.should_post else 1)


if __name__ == "__main__":
    asyncio.run(main())
