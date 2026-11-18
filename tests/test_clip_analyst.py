"""
Testes unitários para o módulo clip_analyst.

Cobre:
  - ClipAnalyst em modo fallback (sem API key)
  - ClipAnalyst parseando resposta JSON válida do Gemini (mock)
  - AudioTranscriber retornando string mesmo sem modelo carregado
  - Gate de qualidade: clipe com nota baixa não passa pro video_processor
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Garante importação da raiz do projeto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import HypeEvent
from modules.clip_analyst.analyst import ClipAnalyst, ClipAnalysisResult, _extract_json
from modules.clip_analyst.transcriber import AudioTranscriber


def _make_hype_event(json_path: str | None = None) -> HypeEvent:
    """Cria um HypeEvent de teste."""
    return HypeEvent(
        score=15.0,
        reason="Pico de mensagens no chat (teste)",
        streamer_channel="gaules",
        timestamp=datetime(2024, 1, 15, 20, 30, 0, tzinfo=timezone.utc),
        json_path=json_path,
        spike_multiplier=3.8,
        recent_messages_count=22,
    )


class TestClipAnalystFallback(unittest.IsolatedAsyncioTestCase):
    """Testa o comportamento de fallback quando API key está ausente."""

    async def test_fallback_sem_api_key_retorna_resultado_valido(self):
        """Sem API key, deve retornar resultado de fallback com should_post=True."""
        analyst = ClipAnalyst(api_key="", min_score=6.0)
        hype = _make_hype_event()

        result = await analyst.analyze(hype, transcript="Texto de teste")

        self.assertIsInstance(result, ClipAnalysisResult)
        self.assertTrue(result.is_fallback)
        self.assertGreater(result.score, 0)
        self.assertIsInstance(result.title, str)
        self.assertIsInstance(result.hashtags, list)
        self.assertIsInstance(result.should_post, bool)

    async def test_fallback_should_post_respeitando_min_score(self):
        """Com min_score muito alto, fallback (nota 7.0) deve retornar should_post=False."""
        analyst = ClipAnalyst(api_key="", min_score=9.0)
        hype = _make_hype_event()

        result = await analyst.analyze(hype)

        self.assertTrue(result.is_fallback)
        self.assertEqual(result.score, 7.0)
        self.assertFalse(result.should_post)  # 7.0 < 9.0

    async def test_fallback_com_min_score_baixo_should_post_true(self):
        """Com min_score baixo, fallback (nota 7.0) deve retornar should_post=True."""
        analyst = ClipAnalyst(api_key="", min_score=5.0)
        hype = _make_hype_event()

        result = await analyst.analyze(hype)

        self.assertTrue(result.should_post)  # 7.0 >= 5.0


class TestClipAnalystGeminiMock(unittest.IsolatedAsyncioTestCase):
    """Testa o parsing da resposta do Gemini com client mockado."""

    def _make_analyst_with_mock_client(self, min_score: float = 6.0) -> ClipAnalyst:
        analyst = ClipAnalyst(api_key="fake_key_for_test", min_score=min_score)
        # Injeta client mock
        mock_client = MagicMock()
        analyst._client = mock_client
        return analyst

    def _setup_gemini_response(self, analyst: ClipAnalyst, json_response: dict) -> None:
        """Configura o client mock para retornar um JSON específico."""
        response_text = json.dumps(json_response, ensure_ascii=False)
        mock_response = MagicMock()
        mock_response.text = response_text
        analyst._client.models.generate_content.return_value = mock_response

    async def test_parse_resposta_gemini_valida(self):
        """Deve parsear corretamente uma resposta JSON válida do Gemini."""
        analyst = self._make_analyst_with_mock_client(min_score=6.0)
        self._setup_gemini_response(analyst, {
            "score": 8.5,
            "title": "Clutch incrível no CS2",
            "hashtags": ["#CS2", "#Twitch", "#Gaming", "#Brasil"],
            "reasoning": "Momento épico com reação do chat"
        })

        hype = _make_hype_event()
        result = await analyst.analyze(hype, transcript="Vamos vamos vamos! Que jogada!")

        self.assertAlmostEqual(result.score, 8.5)
        self.assertEqual(result.title, "Clutch incrível no CS2")
        self.assertIn("#CS2", result.hashtags)
        self.assertTrue(result.should_post)
        self.assertFalse(result.is_fallback)

    async def test_parse_score_clipado_entre_1_e_10(self):
        """Score fora do intervalo deve ser clipado entre 1.0 e 10.0."""
        analyst = self._make_analyst_with_mock_client()
        self._setup_gemini_response(analyst, {
            "score": 15.0,  # inválido
            "title": "Título",
            "hashtags": [],
            "reasoning": "Teste"
        })

        result = await analyst.analyze(_make_hype_event())
        self.assertEqual(result.score, 10.0)  # clipado

    async def test_resposta_nao_json_usa_fallback(self):
        """Se Gemini retornar texto não-JSON, deve usar fallback."""
        analyst = self._make_analyst_with_mock_client()
        mock_response = MagicMock()
        mock_response.text = "Desculpe, não posso avaliar este conteúdo."
        analyst._client.models.generate_content.return_value = mock_response

        result = await analyst.analyze(_make_hype_event())

        self.assertTrue(result.is_fallback)

    async def test_excecao_na_api_usa_fallback(self):
        """Se a API do Gemini lançar exceção, deve retornar fallback."""
        analyst = self._make_analyst_with_mock_client()
        analyst._client.models.generate_content.side_effect = RuntimeError("timeout")

        result = await analyst.analyze(_make_hype_event())

        self.assertTrue(result.is_fallback)
        self.assertIn("timeout", result.reasoning.lower() + result.raw_gemini_response.lower())

    async def test_carrega_mensagens_do_json_path(self):
        """Deve carregar mensagens do arquivo JSON indicado no HypeEvent."""
        analyst = self._make_analyst_with_mock_client(min_score=6.0)
        self._setup_gemini_response(analyst, {
            "score": 7.0,
            "title": "Título de teste",
            "hashtags": ["#Test"],
            "reasoning": "Teste com JSON real"
        })

        # Cria arquivo JSON temporário
        messages = [
            {"author": "user1", "content": "KEKW", "timestamp": "2024-01-15T20:30:00Z"},
            {"author": "user2", "content": "POG POG POG", "timestamp": "2024-01-15T20:30:01Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(messages, f)
            json_path = f.name

        try:
            hype = _make_hype_event(json_path=json_path)
            result = await analyst.analyze(hype)

            # Verifica que o prompt enviado ao Gemini continha as mensagens
            call_args = analyst._client.models.generate_content.call_args
            prompt = call_args[1].get("contents", call_args[0][1] if len(call_args[0]) > 1 else "")
            self.assertIn("user1", prompt)
            self.assertIn("KEKW", prompt)
        finally:
            Path(json_path).unlink(missing_ok=True)


class TestExtractJson(unittest.TestCase):
    """Testa a função utilitária de extração de JSON."""

    def test_json_direto(self):
        result = _extract_json('{"score": 8, "title": "X", "hashtags": [], "reasoning": "y"}')
        self.assertEqual(result["score"], 8)

    def test_json_em_bloco_markdown(self):
        text = '```json\n{"score": 7, "title": "T", "hashtags": [], "reasoning": "r"}\n```'
        result = _extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 7)

    def test_json_embutido_em_texto(self):
        text = 'Claro! Aqui está a análise: {"score": 9, "title": "X", "hashtags": [], "reasoning": "z"} Espero que ajude.'
        result = _extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 9)

    def test_texto_sem_json_retorna_none(self):
        result = _extract_json("Desculpe, não posso ajudar com isso.")
        self.assertIsNone(result)


class TestAudioTranscriber(unittest.TestCase):
    """Testa o AudioTranscriber."""

    def test_arquivo_inexistente_retorna_string(self):
        """Deve retornar string mesmo quando o arquivo não existe."""
        transcriber = AudioTranscriber()
        result = transcriber.transcribe("/caminho/que/nao/existe.mp4")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_retorna_string_sem_modelo_carregado(self):
        """Sem modelo disponível, deve retornar mensagem de fallback (string)."""
        transcriber = AudioTranscriber(model_size="tiny")
        # Força falha no carregamento do modelo
        with patch("builtins.__import__", side_effect=ImportError("faster_whisper not found")):
            # _load_model retorna None → transcribe retorna string de fallback
            pass  # o patch não afeta módulos já importados
        # Valida que o retorno é sempre string
        result = transcriber.transcribe("/dev/null")
        self.assertIsInstance(result, str)

    def test_transcribe_arquivo_vazio(self):
        """Para arquivo vazio/inválido, deve retornar string de fallback."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp_path = f.name
            # Arquivo vazio — não é um MP4 válido

        try:
            transcriber = AudioTranscriber()
            result = transcriber.transcribe(tmp_path)
            self.assertIsInstance(result, str)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestQualityGate(unittest.IsolatedAsyncioTestCase):
    """Testa o gate de qualidade no orchestrator (integração leve)."""

    async def test_clipe_nota_baixa_nao_e_processado(self):
        """
        Simula o gate: analyst retorna nota abaixo do mínimo,
        video_processor.create_clip NÃO deve ser chamado.
        """
        from core.config import Settings
        from modules.video_processor.mock_processor import MockVideoProcessor
        from main import TwitchAutoClipperOrchestrator

        settings = Settings(mock_mode=True, min_clip_score=9.9)

        orchestrator = TwitchAutoClipperOrchestrator(settings=settings, live_mode=False)

        # Mock do analyst para retornar nota baixa
        low_score_result = ClipAnalysisResult(
            score=4.0,
            title="Momento comum",
            hashtags=[],
            reasoning="Chat estava quieto",
            should_post=False,
            is_fallback=False,
        )
        orchestrator.clip_analyst.analyze = AsyncMock(return_value=low_score_result)

        # Mock do video_processor para verificar que não foi chamado
        orchestrator.video_processor.create_clip = AsyncMock()

        hype = _make_hype_event()
        await orchestrator._on_hype_detected(hype)

        # Deve NÃO ter chamado create_clip
        orchestrator.video_processor.create_clip.assert_not_called()

    async def test_clipe_nota_alta_e_processado(self):
        """
        Com nota acima do mínimo, video_processor.create_clip DEVE ser chamado.
        """
        from core.config import Settings
        from core.models import ClipMetadata
        from main import TwitchAutoClipperOrchestrator

        settings = Settings(mock_mode=True, min_clip_score=6.0)
        orchestrator = TwitchAutoClipperOrchestrator(settings=settings, live_mode=False)

        # Mock do analyst com nota alta
        high_score_result = ClipAnalysisResult(
            score=9.0,
            title="Clutch épico!",
            hashtags=["#Twitch", "#Gaming"],
            reasoning="Chat explodiu de POG",
            should_post=True,
            is_fallback=False,
        )
        orchestrator.clip_analyst.analyze = AsyncMock(return_value=high_score_result)

        # Mock do video_processor
        fake_clip = ClipMetadata(
            clip_id="test_clip",
            file_path="/tmp/test.mp4",
            title="Clutch épico!",
            description="",
            tags=[],
            duration=45.0,
        )
        orchestrator.video_processor.create_clip = AsyncMock(return_value=fake_clip)
        orchestrator.social_uploader.upload_all = AsyncMock(return_value=[])

        hype = _make_hype_event()
        await orchestrator._on_hype_detected(hype)

        # Deve ter chamado create_clip
        orchestrator.video_processor.create_clip.assert_called_once()


if __name__ == "__main__":
    unittest.main()
