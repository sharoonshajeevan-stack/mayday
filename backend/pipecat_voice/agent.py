# ============================================================================
# MAYDAY OS - REAL-TIME VOICE AGENT
# File: backend/pipecat_voice/agent.py
# Purpose: Assemble and run the Pipecat pipeline that powers MAYDAY's
#          real-time voice mode.
#
# Pipeline (the canonical Pipecat voice shape):
#
#   transport.input()
#     -> MaydayWhisperSTTService      (existing Faster-Whisper)
#     -> LLMUserAggregator            (VAD + turn detection -> user turns)
#     -> MaydayLLMService             (existing command router + Gemini/Ollama)
#     -> MaydayKokoroTTSService       (existing Kokoro-82M, streaming)
#     -> transport.output()
#     -> LLMAssistantAggregator       (records replies back into context)
#
# Barge-in is automatic: Silero VAD detects the user speaking while MAYDAY is
# talking and Pipecat interrupts the LLM + TTS and flushes pending audio.
# ============================================================================

import asyncio
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from pipecat_voice.events import STATE_ERROR, STATE_IDLE, STATE_LISTENING
from pipecat_voice.llm_adapter import MaydayLLMService
from pipecat_voice.observer import VoiceStateObserver
from pipecat_voice.stt_adapter import MaydayWhisperSTTService
from pipecat_voice.tts_adapter import MaydayKokoroTTSService

logger = logging.getLogger(__name__)

# How long to wait for a graceful pipeline shutdown before forcing it.
STOP_TIMEOUT_SECS = 15.0


class MaydayVoiceAgent:
    """Owns the lifecycle of one real-time voice session."""

    def __init__(self, config, hub, *, stt_engine, tts_engine):
        self.config = config
        self.hub = hub
        self._stt_engine = stt_engine
        self._tts_engine = tts_engine

        self._runner = None
        self._worker = None
        self._run_future = None
        self._running = False

        self._context = None
        self._user_aggregator = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit(self, event_type, **payload):
        self.hub.emit(event_type, **payload)

    @property
    def is_running(self):
        return self._running

    def status(self):
        return {
            "running": self._running,
            "transport": self.config.transport,
            "state": self.hub.state,
            "clients": self.hub.client_count,
            "sample_rates": {
                "input": self.config.audio_in_sample_rate,
                "output": self.config.audio_out_sample_rate,
            },
        }

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _make_transport(self):
        if self.config.transport != "local":
            raise ValueError(
                f"Unsupported transport '{self.config.transport}'. "
                "Only 'local' is enabled."
            )

        from pipecat.transports.local.audio import (
            LocalAudioTransport,
            LocalAudioTransportParams,
        )

        params = LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=self.config.audio_in_sample_rate,
            audio_out_sample_rate=self.config.audio_out_sample_rate,
            audio_in_channels=1,
            audio_out_channels=1,
            input_device_index=self.config.input_device_index,
            output_device_index=self.config.output_device_index,
        )
        return LocalAudioTransport(params)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    def build_worker(self, transport):
        stt = MaydayWhisperSTTService(
            engine=self._stt_engine,
            trailing_silence_secs=self.config.stt_trailing_silence_secs,
        )
        tts = MaydayKokoroTTSService(engine=self._tts_engine)
        llm = MaydayLLMService(event_hook=self._emit)

        self._context = LLMContext()
        aggregators = LLMContextAggregatorPair(
            self._context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        confidence=self.config.vad_confidence,
                        start_secs=self.config.vad_start_secs,
                        stop_secs=self.config.vad_stop_secs,
                        min_volume=self.config.vad_min_volume,
                    ),
                ),
                user_turn_strategies=UserTurnStrategies(),
                user_turn_stop_timeout=self.config.user_turn_stop_timeout,
            ),
        )
        self._user_aggregator = aggregators.user()

        observer = VoiceStateObserver(event_hook=self._emit)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                aggregators.user(),
                llm,
                tts,
                transport.output(),
                aggregators.assistant(),
            ]
        )

        return PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=self.config.audio_in_sample_rate,
                audio_out_sample_rate=self.config.audio_out_sample_rate,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[observer],
            # Continuous listening: never auto-cancel a quiet session.
            idle_timeout_secs=None,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self):
        if self._running:
            return self.status()

        try:
            transport = self._make_transport()
        except Exception as exc:  # noqa: BLE001 - no audio device, etc.
            logger.exception("Could not open the local audio transport")
            self._emit("error", message=f"Audio device unavailable: {exc}")
            self._emit("state", state=STATE_ERROR)
            raise

        self._runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
        self._worker = self.build_worker(transport)
        await self._runner.add_workers(self._worker)
        self._run_future = asyncio.create_task(self._run())
        self._running = True

        self._emit("listening", value=True)
        self._emit("state", state=STATE_LISTENING)
        logger.info("MAYDAY real-time voice session started")
        return self.status()

    async def _run(self):
        try:
            await self._runner.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Voice pipeline stopped with an error")
            self._emit("error", message=str(exc))
        finally:
            self._running = False
            self._emit("listening", value=False)
            self._emit("state", state=STATE_IDLE)
            logger.info("MAYDAY real-time voice session stopped")

    async def stop(self):
        if not self._running:
            return self.status()

        self._emit("listening", value=False)

        worker = self._worker
        self._worker = None

        if worker is not None:
            try:
                await worker.stop_when_done()
            except Exception:  # noqa: BLE001
                logger.debug("stop_when_done failed", exc_info=True)

        run_future = self._run_future
        self._run_future = None

        if run_future is not None:
            try:
                await asyncio.wait_for(asyncio.shield(run_future), STOP_TIMEOUT_SECS)
            except asyncio.TimeoutError:
                logger.warning("Voice pipeline did not stop in time; cancelling")
                run_future.cancel()
            except Exception:  # noqa: BLE001
                run_future.cancel()

        self._running = False
        self._runner = None
        self._emit("state", state=STATE_IDLE)
        return self.status()

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    async def interrupt(self):
        """Barge-in: stop the current reply and any pending audio."""
        worker = self._worker
        if worker is None:
            return False
        await worker.queue_frame(InterruptionFrame())
        return True

    async def send_text(self, text):
        """Inject a typed utterance as if it had been spoken."""
        text = str(text or "").strip()
        if not text or not self._running or self._user_aggregator is None:
            return False

        self._context.add_message({"role": "user", "content": text})
        self._emit("transcript", text=text, final=True)
        await self._user_aggregator.push_context_frame()
        return True

    async def speak(self, text):
        """Speak text directly (no LLM round-trip)."""
        text = str(text or "").strip()
        worker = self._worker
        if not text or worker is None:
            return False
        await worker.queue_frame(TTSSpeakFrame(text))
        return True
