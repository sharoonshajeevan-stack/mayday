# ============================================================================
# MAYDAY OS - PIPECAT MUTE (PLAYBACK) PROCESSOR
# File: backend/pipecat_voice/mute.py
# Purpose: Let the user silence MAYDAY's spoken output without ending the
#          session, so MAYDAY stays available (and still shows the reply on
#          screen) in a quiet room, a meeting, or late at night.
#
# The processor sits between the Kokoro TTS service and the output transport
# and replaces outgoing audio with silence of *exactly* the same length. That
# keeps playback timing, metrics and the SPEAKING state identical - only the
# sound disappears. Barge-in still works while muted.
# ============================================================================

import logging

from pipecat.frames.frames import TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameProcessor

logger = logging.getLogger(__name__)


class MuteProcessor(FrameProcessor):
    """Silence outgoing TTS audio on demand, keeping the pipeline timing."""

    def __init__(self, *, muted=False, **kwargs):
        super().__init__(**kwargs)
        self._muted = bool(muted)

    @property
    def muted(self):
        return self._muted

    def set_muted(self, value):
        """Enable/disable playback silencing. Returns the new value."""
        self._muted = bool(value)
        logger.info("MAYDAY voice playback %s", "muted" if self._muted else "unmuted")
        return self._muted

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if self._muted and isinstance(frame, TTSAudioRawFrame):
            # Zeroing in place keeps every timing field (id/pts/metadata) so
            # the transport plays silence for the same duration.
            frame.audio = b"\x00" * len(frame.audio)

        await self.push_frame(frame, direction)
