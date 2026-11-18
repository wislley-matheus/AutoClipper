"""
Análise de qualidade de clipes via Gemini AI.

O ClipAnalyst lê as mensagens do chat + a transcrição de áudio e chama o
modelo Gemini para gerar uma nota (1-10) e um título viral com hashtags.

Usa o novo SDK google-genai (google.genai), não o depreciado google-generativeai.
Fallback automático quando não há chave de API configurada.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.models import HypeEvent

logger = logging.getLogger(__name__)

# Template do prompt enviado ao Gemini
_PROMPT_TEMPLATE = """Você é um especialista em conteúdo viral para Twitch/YouTube Shorts/TikTok.

DADOS DO MOMENTO VIRAL:
- Canal: {channel}
- Pico detectado: {spike_multiplier:.1f}x acima da média normal ({messages_count} msgs em 5s)
- Razão do disparo: {reason}
- Timestamp: {timestamp}

ÚLTIMAS {n} MENSAGENS DO CHAT:
{chat_json}

TRANSCRIÇÃO DO ÁUDIO DO CLIPE:
{transcript}

Analise o momento e responda APENAS com JSON válido (sem markdown, sem texto extra):
{{
  "score": <número de 1 a 10, sendo 10 o máximo potencial viral>,
  "title": "<título viral em português, max 80 chars, sem emoji>",
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
  "reasoning": "<explicação curta de 1 linha>"
}}

Critérios de pontuação:
- 8-10: Momento épico (clutch, record, highlight incrível, reação extrema)
- 5-7: Momento bom (reação divertida, jogada interessante, interação com chat)
- 1-4: Momento comum (não vale postar)
"""


@dataclass
class ClipAnalysisResult:
    """Resultado da análise do Gemini para um clipe."""

    score: float = 5.0
    title: str = ""
    hashtags: List[str] = field(default_factory=list)
    reasoning: str = ""
    should_post: bool = True
    raw_gemini_response: str = ""
    is_fallback: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "title": self.title,
            "hashtags": self.hashtags,
            "reasoning": self.reasoning,
            "should_post": self.should_post,
            "is_fallback": self.is_fallback,
            "analyzed_at": self.analyzed_at,
        }

    def __str__(self) -> str:
        status = "✅ POSTAR" if self.should_post else "❌ DESCARTAR"
        fallback_note = " [fallback]" if self.is_fallback else ""
        return (
            f"[ClipAnalyst{fallback_note}] Nota: {self.score:.1f}/10 → {status}\n"
            f"  Título: {self.title}\n"
            f"  Hashtags: {' '.join(self.hashtags)}\n"
            f"  Motivo: {self.reasoning}"
        )


def _make_fallback_result(min_score: float, reason: str = "Fallback automático") -> ClipAnalysisResult:
    """Cria um resultado de fallback quando o Gemini não está disponível."""
    return ClipAnalysisResult(
        score=7.0,
        title="Momento épico na Twitch",
        hashtags=["#Twitch", "#Clip", "#Gaming", "#Brasil", "#Shorts"],
        reasoning=reason,
        should_post=7.0 >= min_score,
        is_fallback=True,
    )


def _extract_json(text: str) -> Optional[dict]:
    """Extrai o primeiro bloco JSON válido do texto retornado pelo Gemini."""
    # Remove blocos de código markdown se presentes
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.strip()

    # Tenta parse direto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tenta encontrar bloco JSON entre { }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


class ClipAnalyst:
    """
    Analisa clipes usando Gemini AI para decidir se valem upload.

    Uso:
        analyst = ClipAnalyst(api_key="...", min_score=6.0)
        result = await analyst.analyze(hype_event, transcript="Texto do áudio")
        if result.should_post:
            # renderizar e fazer upload
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        min_score: float = 6.0,
        channel: str = "desconhecido",
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.min_score = min_score
        self.channel = channel
        self._client = None

    def _get_client(self):
        """Inicializa o cliente Gemini (lazy loading)."""
        if self._client is not None:
            return self._client

        if not self.api_key:
            logger.warning("GEMINI_API_KEY não configurada — modo fallback ativado.")
            return None

        try:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
            logger.info("Cliente Gemini inicializado (modelo: %s).", self.model_name)
            return self._client
        except ImportError:
            logger.error("Pacote google-genai não instalado. Use: pip install google-genai")
            return None
        except Exception as exc:
            logger.error("Falha ao inicializar cliente Gemini: %s", exc)
            return None

    def _load_chat_messages(self, json_path: Optional[str]) -> List[dict]:
        """Carrega as mensagens do chat salvas pelo hype_detector."""
        if not json_path:
            return []
        path = Path(json_path)
        if not path.exists():
            logger.warning("Arquivo de mensagens não encontrado: %s", json_path)
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # suporta tanto lista direta quanto {"messages": [...]}
            if isinstance(data, list):
                return data
            return data.get("messages", data.get("recent_messages", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Erro ao ler mensagens do chat: %s", exc)
            return []

    def _build_prompt(self, hype_event: HypeEvent, transcript: str, messages: List[dict]) -> str:
        """Monta o prompt para o Gemini."""
        # Formata mensagens de forma legível
        if messages:
            chat_lines = []
            for msg in messages[-40:]:  # máximo 40 mensagens
                user = msg.get("author", msg.get("username", "?"))
                text = msg.get("content", msg.get("text", msg.get("message", "")))
                chat_lines.append(f"  {user}: {text}")
            chat_json = "\n".join(chat_lines)
        else:
            chat_json = "  [Sem mensagens disponíveis]"

        return _PROMPT_TEMPLATE.format(
            channel=self.channel,
            spike_multiplier=hype_event.spike_multiplier,
            messages_count=hype_event.recent_messages_count,
            reason=hype_event.reason,
            timestamp=hype_event.timestamp.isoformat(),
            n=len(messages),
            chat_json=chat_json,
            transcript=transcript or "[Transcrição indisponível]",
        )

    async def analyze(
        self,
        hype_event: HypeEvent,
        transcript: str = "",
        video_path: Optional[str] = None,
    ) -> ClipAnalysisResult:
        """
        Analisa o clipe e retorna nota + título viral.

        Args:
            hype_event: Evento de hype detectado (com json_path para as mensagens).
            transcript: Transcrição do áudio (pode ser vazio).
            video_path: Não usado diretamente; reservado para análise futura de frames.

        Returns:
            ClipAnalysisResult com score, title, hashtags e should_post.
        """
        client = self._get_client()
        if client is None:
            return _make_fallback_result(self.min_score, "API key ausente ou cliente indisponível")

        messages = self._load_chat_messages(hype_event.json_path)
        prompt = self._build_prompt(hype_event, transcript, messages)

        try:
            logger.info("Enviando clipe para análise Gemini (modelo: %s)...", self.model_name)
            from google import genai

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )

            raw_text = response.text or ""
            logger.debug("Resposta bruta do Gemini: %s", raw_text[:500])

            parsed = _extract_json(raw_text)
            if parsed is None:
                logger.warning("Gemini não retornou JSON válido. Usando fallback.")
                return _make_fallback_result(self.min_score, "Resposta Gemini não parseável")

            score = float(parsed.get("score", 5.0))
            score = max(1.0, min(10.0, score))  # clipa entre 1 e 10

            result = ClipAnalysisResult(
                score=score,
                title=str(parsed.get("title", "Momento incrível na Twitch"))[:80],
                hashtags=list(parsed.get("hashtags", ["#Twitch", "#Gaming"])),
                reasoning=str(parsed.get("reasoning", "")),
                should_post=score >= self.min_score,
                raw_gemini_response=raw_text,
                is_fallback=False,
            )

            logger.info("Análise concluída: %s", result)
            return result

        except Exception as exc:
            logger.exception("Erro na chamada ao Gemini: %s", exc)
            return _make_fallback_result(self.min_score, f"Erro na API: {exc}")

    def analyze_sync(
        self,
        hype_event: HypeEvent,
        transcript: str = "",
    ) -> ClipAnalysisResult:
        """
        Versão síncrona do analyze() — útil para chamadas em contextos não-async.
        """
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.analyze(hype_event, transcript))
        finally:
            loop.close()
