# ============================================================================
# MAYDAY OS - REAL-TIME VOICE (Pipecat)
# File: backend/pipecat_voice/__init__.py
# Purpose: Real-time voice orchestration layer for MAYDAY.
#
# This package adds continuous listening, voice-activity detection, turn
# detection, barge-in / interruption and streaming speech on top of the
# *existing* MAYDAY engines. It does not replace them:
#
#   Faster-Whisper (speech_to_text.py)  ->  MaydayWhisperSTTService
#   Kokoro-82M     (text_to_speech.py)  ->  MaydayKokoroTTSService
#   Gemini/Ollama  (ai_engine.py)       ->  MaydayLLMService
#
# Everything is orchestrated by Pipecat (https://github.com/pipecat-ai/pipecat)
# in a separate, self-contained service process so the Flask backend and the
# React front-end keep working exactly as before.
# ============================================================================

__all__ = [
    "config",
    "events",
    "stt_adapter",
    "tts_adapter",
    "llm_adapter",
    "observer",
    "agent",
    "control_server",
    "service",
]
