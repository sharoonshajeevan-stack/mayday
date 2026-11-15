# ============================================================================
# MAYDAY OS - PIPECAT VOICE STATE OBSERVER
# File: backend/pipecat_voice/observer.py
# Purpose: Translate the stream of Pipecat frames into the simple voice
#          states and events the MAYDAY HUD understands.
#
# States: IDLE, LISTENING, THINKING, SPEAKING, EXECUTING, ERROR
# Events: state, transcript, response, interrupted, error, metrics
# ============================================================================

import logging

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from pipecat_voice.events import (
    STATE_ERROR,
    STATE_LISTENING,
    STATE_SPEAKING,
    STATE_THINKING,
)

logger = logging.getLogger(__name__)

try:  # MetricsFrame moved around between Pipecat releases.
    from pipecat.frames.frames import MetricsFrame
except ImportError:  # pragma: no cover
    MetricsFrame = None


class VoiceStateObserver(BaseObserver):
    """Maps pipeline frames to MAYDAY voice states."""

    def __init__(self, *, event_hook, **kwargs):
        super().__init__(observe_every_push=False, **kwargs)
        self._event_hook = event_hook
        self._state = None
        self._interrupt_emitted = False

    # ------------------------------------------------------------------
    def _set_state(self, state):
        if state == self._state:
            return
        self._state = state
        self._event_hook("state", state=state)

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        # --- User speech ---------------------------------------------------
        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._interrupt_emitted = False
            self._set_state(STATE_LISTENING)
            return

        if isinstance(frame, InterimTranscriptionFrame):
            self._event_hook("transcript", text=frame.text, final=False)
            return

        if isinstance(frame, TranscriptionFrame):
            self._event_hook("transcript", text=frame.text, final=True)
            self._set_state(STATE_THINKING)
            return

        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            self._set_state(STATE_THINKING)
            return

        # --- Assistant speech ---------------------------------------------
        if isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self._set_state(STATE_SPEAKING)
            return

        if isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self._set_state(STATE_LISTENING)
            return

        # --- Interruption ---------------------------------------------------
        if isinstance(frame, InterruptionFrame):
            if not self._interrupt_emitted:
                self._interrupt_emitted = True
                self._event_hook("interrupted")
            self._set_state(STATE_LISTENING)
            return

        # --- Errors ---------------------------------------------------------
        if isinstance(frame, ErrorFrame):
            self._event_hook("error", message=getattr(frame, "error", str(frame)))
            self._set_state(STATE_ERROR)
            return

        # --- Performance metrics -------------------------------------------
        if MetricsFrame is not None and isinstance(frame, MetricsFrame):
            try:
                self._event_hook(
                    "metrics",
                    data=[m.model_dump() for m in frame.data],
                )
            except Exception:  # noqa: BLE001
                logger.debug("Could not serialise metrics frame")
