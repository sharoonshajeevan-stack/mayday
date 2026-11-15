# ============================================================================
# MAYDAY OS - PIPECAT LLM ADAPTER
# File: backend/pipecat_voice/llm_adapter.py
# Purpose: Bridge MAYDAY's existing "brain" (command router + Gemini/Ollama +
#          personality + memory) into Pipecat as an LLM service.
#
# There is deliberately no second model here. When the user's turn closes,
# Pipecat hands us an LLMContextFrame; we run the same
# ``mayday_brain.handle_utterance`` the Flask /api/command route uses, in a
# worker thread so the pipeline never blocks, then stream the reply text to
# the TTS service.
#
# Interruptions: Pipecat's LLMService handles InterruptionFrame on its own
# task and cancels this generation, so a barge-in aborts the reply (and the
# downstream TTS) immediately.
# ============================================================================

import asyncio
import logging

from pipecat.frames.frames import (
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from mayday_brain import handle_utterance

logger = logging.getLogger(__name__)

# MAYDAY owns its own prompt, temperature and model selection (Gemini or
# Ollama), so every provider-specific knob is declared unsupported here. They
# must still be listed explicitly or Pipecat logs a settings warning.
MAYDAY_LLM_SETTINGS = LLMSettings(
    model="mayday-brain",
    system_instruction=None,
    temperature=None,
    max_tokens=None,
    top_p=None,
    top_k=None,
    frequency_penalty=None,
    presence_penalty=None,
    seed=None,
    filter_incomplete_user_turns=None,
    user_turn_completion_config=None,
)


def _extract_text(content):
    """Pull plain text out of a context message's content field."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts).strip()

    return ""


class MaydayLLMService(LLMService):
    """Pipecat LLM service backed by MAYDAY's existing AI engine."""

    def __init__(self, *, event_hook=None, **kwargs):
        kwargs.setdefault("settings", MAYDAY_LLM_SETTINGS)
        super().__init__(**kwargs)
        self._event_hook = event_hook or (lambda *args, **kwargs: None)

    # ------------------------------------------------------------------
    # Frame handling
    # ------------------------------------------------------------------
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            await self._respond(frame.context)
        else:
            await self.push_frame(frame, direction)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @staticmethod
    def _latest_user_text(context):
        try:
            messages = context.get_messages()
        except Exception:  # noqa: BLE001
            return ""

        for message in reversed(messages or []):
            if str(message.get("role")) == "user":
                text = _extract_text(message.get("content"))
                if text:
                    return text

        return ""

    async def _respond(self, context):
        text = self._latest_user_text(context)

        if not text:
            return

        await self.push_frame(LLMFullResponseStartFrame())

        # Only close the turn (push the end frame) when we actually finish.
        # On interruption this coroutine is cancelled and we must *not* await
        # anything further - the pipeline is already tearing the turn down.
        completed = False

        try:
            self._event_hook("state", state="THINKING")

            result = await asyncio.to_thread(handle_utterance, text)

            spoken = (result.get("spoken") or result.get("response") or "").strip()
            written = (result.get("response") or spoken).strip()

            if result.get("kind"):
                self._event_hook(
                    "executing",
                    action_kind=result.get("kind"),
                    command=result.get("command"),
                )

            self._event_hook(
                "response",
                text=written,
                spoken=spoken,
                source=result.get("source"),
                status=result.get("status"),
            )

            if spoken:
                await self.push_frame(LLMTextFrame(spoken))

            completed = True
        except asyncio.CancelledError:
            logger.debug("MAYDAY reply cancelled (interruption)")
            raise
        except Exception as exc:  # noqa: BLE001 - never kill the pipeline
            logger.exception("MAYDAY brain failed")
            self._event_hook("error", message=str(exc))
            await self.push_error(error_msg=f"MAYDAY brain error: {exc}", exception=exc)
            completed = True
        finally:
            if completed:
                await self.push_frame(LLMFullResponseEndFrame())
