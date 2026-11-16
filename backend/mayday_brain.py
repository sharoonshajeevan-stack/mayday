# ============================================================================
# MAYDAY OS - CONVERSATION BRAIN (shared)
# File: backend/mayday_brain.py
# Purpose: Resolve a single utterance end-to-end exactly like the Flask
#          /api/command route does, so spoken (real-time Pipecat) and typed
#          commands behave identically.
#
# Flow:  memory commands  ->  deterministic command router
#        ->  AI engine (Gemini / Ollama, with retrieved memory context)
#        ->  personality commentary  ->  smart memory
#
# This module intentionally contains *no* new model, no duplicate memory store
# and no UI logic. It only re-uses the existing MAYDAY pieces:
#   memory_manager.handle_memory_command (persistent long-term memory commands)
#   command_router.route_command  (system actions)
#   ai_engine.process_ai_command  (online Gemini / offline Ollama)
#   personality.comment_on_action (local, deterministic commentary)
#   memory_system.add_memory      (rolling conversation log)
# ============================================================================

import logging
from datetime import datetime

from action_result import format_action_result
from ai_engine import process_ai_command
from command_router import route_command
from memory_manager import handle_memory_command, memory_manager
from memory_system import add_memory
from personality import comment_on_action

logger = logging.getLogger(__name__)


def remember_conversation(user_input, ai_response, tags=None):
    """Store an exchange so MAYDAY can follow up on it later (best effort)."""
    try:
        add_memory(
            str(user_input or "")[:2000],
            str(ai_response or "")[:4000],
            tags or [],
        )
    except Exception as exc:  # noqa: BLE001 - memory must never break a reply
        logger.warning("Could not record conversation memory: %s", exc)


def _observe(user_input, ai_response):
    """Extract and persist any long-term facts from an exchange (best effort)."""
    try:
        memory_manager.observe(user_input, ai_response)
    except Exception as exc:  # noqa: BLE001 - memory must never break a reply
        logger.warning("Could not update long-term memory: %s", exc)


def _memory_context(text):
    """Return a compact block of relevant long-term memories (best effort)."""
    try:
        return memory_manager.retrieve_context(text) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not retrieve long-term memory: %s", exc)
        return ""


def handle_utterance(text):
    """Turn one user utterance into a reply.

    Returns a dict:
        {
          "status": "success" | "error",
          "command": <original text>,
          "response": <full text for the screen>,
          "spoken": <short text to speak>,
          "source": "system" | "online" | "offline" | "memory" | ...,
          "kind": <action kind> (only for routed system actions),
          "timestamp": <iso8601>,
        }

    The function never raises: failures come back as ``status == "error"`` so
    the real-time pipeline can keep listening.
    """
    text = str(text or "").strip()

    if not text:
        return {
            "status": "error",
            "command": "",
            "response": "",
            "spoken": "",
            "error": "empty utterance",
            "timestamp": datetime.now().isoformat(),
        }

    # 1. Explicit memory commands ("remember this", "show my project memories")
    #    act directly on the persistent database.
    try:
        memory_reply = handle_memory_command(text)
    except Exception as exc:  # noqa: BLE001 - never break the reply path
        logger.error("Memory command failed: %s", exc)
        memory_reply = None

    if memory_reply:
        memory_manager.note_exchange(text, memory_reply.get("response") or "")
        remember_conversation(text, memory_reply.get("response") or "")
        memory_reply["command"] = text
        memory_reply["timestamp"] = datetime.now().isoformat()
        return memory_reply

    # 2. Deterministic system actions.
    try:
        action = route_command(text)
    except Exception as exc:  # noqa: BLE001 - router failures fall through to AI
        logger.error("Command router failed: %s", exc)
        action = None

    if action:
        try:
            formatted = format_action_result(action) or {}
            base_message = formatted.get("response") or "Command completed."
            commentary = comment_on_action(action, text, base_message=base_message)
            result = {
                "status": "success",
                "command": text,
                "response": commentary.get("response") or base_message,
                "spoken": commentary.get("spoken") or base_message,
                "source": "system",
                "kind": commentary.get("kind"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Action commentary failed: %s", exc)
            result = {
                "status": "success",
                "command": text,
                "response": "Done.",
                "spoken": "Done.",
                "source": "system",
            }
    else:
        # 3. Natural language: hand the model the few memories that matter.
        params = {}
        context = _memory_context(text)
        if context:
            params["memory_context"] = context

        try:
            ai = process_ai_command(text, params) or {}
        except Exception as exc:  # noqa: BLE001
            logger.error("AI engine failed: %s", exc)
            ai = {"status": "error", "error": str(exc)}

        if ai.get("status") != "success":
            fallback = ai.get("response") or "I couldn't process that."
            result = {
                "status": "error",
                "command": text,
                "response": fallback,
                "spoken": ai.get("spoken") or fallback,
                "source": ai.get("source") or "ai",
                "error": ai.get("error") or "ai engine error",
            }
            remember_conversation(text, result["response"])
            _observe(text, result["response"])
            result["timestamp"] = datetime.now().isoformat()
            return result

        result = {
            "status": "success",
            "command": text,
            "response": ai.get("response") or "",
            "spoken": ai.get("spoken") or ai.get("response") or "",
            "source": ai.get("source") or ai.get("mode") or "ai",
            "mode": ai.get("mode"),
        }

    remember_conversation(text, result.get("response"))
    _observe(text, result.get("response"))
    result["timestamp"] = datetime.now().isoformat()
    return result
