# ============================================================================
# MAYDAY OS - PIPECAT TTS ADAPTER
# File: backend/pipecat_voice/tts_adapter.py
# Purpose: Expose MAYDAY's existing Kokoro-82M engine to Pipecat as a
#          streaming TTS service.
#
# Kokoro synthesis happens on a worker thread (it is blocking CPU work) and
# is bridged into an async generator. Pipecat plays the yielded audio through
# the output transport and, crucially, cancels the generator on an
# interruption - which flips ``stop_event`` so synthesis stops immediately and
# no further audio is produced or replayed.
# ============================================================================

import asyncio
import logging
import threading

import numpy as np

from pipecat.frames.frames import TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

logger = logging.getLogger(__name__)

# Kokoro-82M native output rate (matches text_to_speech.SAMPLE_RATE).
MAYDAY_TTS_SAMPLE_RATE = 24000


def _float_to_pcm16(audio):
    """Convert a float32 [-1, 1] array to little-endian 16-bit PCM bytes."""
    clipped = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


class MaydayKokoroTTSService(TTSService):
    """Pipecat TTS service backed by MAYDAY's Kokoro-82M engine."""

    def __init__(self, *, engine, sample_rate=MAYDAY_TTS_SAMPLE_RATE, **kwargs):
        kwargs.setdefault(
            "settings",
            TTSSettings(
                model="kokoro-82m",
                voice=getattr(engine, "voice", None),
                language=None,
            ),
        )
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )
        self._engine = engine

    async def run_tts(self, text, context_id):
        """Stream Kokoro audio for ``text`` as Pipecat audio frames."""
        stop_event = threading.Event()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        chunks = self._engine.iter_audio_chunks(text, stop_event=stop_event)

        def produce():
            try:
                for chunk in chunks:
                    if stop_event.is_set():
                        break

                    pcm = _float_to_pcm16(chunk)
                    loop.call_soon_threadsafe(queue.put_nowait, pcm)
            except Exception as exc:  # noqa: BLE001
                logger.error("MAYDAY TTS synthesis failed: %s", exc)
            finally:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                except RuntimeError:
                    # Loop already closed during shutdown.
                    pass

        thread = threading.Thread(target=produce, name="mayday-tts", daemon=True)
        thread.start()

        try:
            while True:
                pcm = await queue.get()

                if pcm is None:
                    break

                yield TTSAudioRawFrame(
                    audio=pcm,
                    sample_rate=MAYDAY_TTS_SAMPLE_RATE,
                    num_channels=1,
                    context_id=context_id,
                )
        finally:
            # Runs on normal completion *and* on interruption/cancellation:
            # flip the stop flag so synthesis halts, then close the engine
            # generator so it releases its synthesis lock immediately.
            stop_event.set()
            try:
                chunks.close()
            except Exception:  # noqa: BLE001
                pass
