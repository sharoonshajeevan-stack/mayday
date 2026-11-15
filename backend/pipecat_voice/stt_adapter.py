# ============================================================================
# MAYDAY OS - PIPECAT STT ADAPTER
# File: backend/pipecat_voice/stt_adapter.py
# Purpose: Expose MAYDAY's existing Faster-Whisper engine to Pipecat as a
#          segmented STT service.
#
# Pipecat's SegmentedSTTService buffers each spoken turn (segmented by VAD)
# and hands us one 16 kHz PCM block per utterance, which is exactly what
# Faster-Whisper wants. No second model is loaded and no chunked/streaming
# transcription is faked: we transcribe whole utterances and emit a single
# final TranscriptionFrame, so words are never duplicated or split.
# ============================================================================

import asyncio
import logging

import numpy as np

from pipecat.frames.frames import TranscriptionFrame
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601

logger = logging.getLogger(__name__)

# Faster-Whisper in MAYDAY runs on 16 kHz mono audio.
MAYDAY_STT_SAMPLE_RATE = 16000


class MaydayWhisperSTTService(SegmentedSTTService):
    """Pipecat STT service backed by MAYDAY's Faster-Whisper engine."""

    def __init__(
        self,
        *,
        engine,
        sample_rate=MAYDAY_STT_SAMPLE_RATE,
        trailing_silence_secs=0.4,
        **kwargs,
    ):
        kwargs.setdefault(
            "settings",
            STTSettings(model="faster-whisper", language=None),
        )
        super().__init__(
            sample_rate=sample_rate,
            trailing_silence_secs=trailing_silence_secs,
            **kwargs,
        )
        self._engine = engine

    @property
    def wants_wav_segments(self):
        # Faster-Whisper takes a raw float32 array; we do the conversion.
        return False

    @property
    def segment_sample_rate(self):
        return MAYDAY_STT_SAMPLE_RATE

    async def run_stt(self, audio: bytes):
        """Transcribe one utterance segment and yield a final frame."""
        if not audio:
            return

        array = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            text = await asyncio.to_thread(self._engine.transcribe_array, array)
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            logger.error("MAYDAY STT failed: %s", exc)
            return

        text = (text or "").strip()

        if text:
            yield TranscriptionFrame(
                text,
                self._user_id or "",
                time_now_iso8601(),
            )
