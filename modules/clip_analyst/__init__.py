"""
Módulo clip_analyst — análise de qualidade de clipes via Gemini AI.

Fluxo:
  1. AudioTranscriber extrai e transcreve o áudio do vídeo (faster-whisper).
  2. ClipAnalyst lê as mensagens do chat + transcrição e chama o Gemini para
     atribuir uma nota (1-10) e gerar título viral + hashtags.
  3. Se a nota >= min_score, o clipe segue para renderização e upload.
"""
from .analyst import ClipAnalyst, ClipAnalysisResult
from .transcriber import AudioTranscriber

__all__ = ["ClipAnalyst", "ClipAnalysisResult", "AudioTranscriber"]
