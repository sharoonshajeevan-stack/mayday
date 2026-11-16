# ============================================================================
# MAYDAY OS - AI ENGINE
# File: backend/ai_engine.py
# Purpose: Route commands to local or online AI according to voice mode.
# ============================================================================

import logging
from datetime import datetime

from ollama_service import chat_with_ollama, get_ollama_status
from voice_mode import get_active_voice_mode, get_voice_mode_status
from online_service import generate_online_response, get_online_status
from personality import build_system_prompt, shorten_for_speech
from memory_system import get_recent_memories

logger = logging.getLogger(__name__)

# How many previous exchanges are replayed to the model so MAYDAY can follow
# up on things like "open YouTube" then "play Arijit Singh".
HISTORY_EXCHANGES = 6


class AIEngine:
    """
    Central AI router.

    Local/offline mode -> Ollama
    Online mode       -> OpenAI Responses API
    Auto mode         -> selected by VoiceModeManager
    """

    def __init__(self):
        self.engine_name = "MAYDAY OS AI Engine v2.0"
        self.is_active = True
        self.command_history = []
        self.max_history = 100
        # The live system prompt is built per request by the personality layer
        # (see backend/personality.py). This short string is only a fallback for
        # callers that read `engine.system_prompt` directly.
        self.system_prompt = (
            "You are MAYDAY, a sophisticated, witty and observant personal AI "
            "companion running on the user's Windows PC. Keep spoken replies "
            "short by default and never restate the user's question."
        )

        logger.info("AI Engine initialized")

    def process_command(self, command, params=None):
        params = params or {}
        command = str(command or "").strip()

        if not command:
            return {
                "status": "error",
                "message": "No command provided",
                "timestamp": datetime.now().isoformat(),
            }

        try:
            command_lower = command.lower()
            mode = get_active_voice_mode()
            spoken = None

            logger.info("Processing command in %s mode: %s", mode, command)

            self._add_to_history({
                "command": command,
                "mode": mode,
                "timestamp": datetime.now().isoformat(),
                "status": "processed",
            })

            # Keep deterministic local utility commands local.
            if self._is_status_request(command_lower):
                response = self._handle_status_request()
                spoken = self._handle_status_spoken()
                source = "local"
            elif self._is_time_request(command_lower):
                response = self._handle_time_request()
                spoken = response
                source = "local"
            elif self._is_help_request(command_lower):
                response = self._handle_help_request()
                spoken = self._handle_help_spoken()
                source = "local"
            elif self._is_greeting(command_lower):
                response = self._handle_greeting(command_lower)
                spoken = response
                source = "local"
            else:
                result = self._generate_ai_response(command, params, mode)
                if result["status"] != "success":
                    return {
                        "status": "error",
                        "command": command,
                        "mode": mode,
                        "source": result.get("source"),
                        "error": result.get("message", "AI request failed"),
                        # A short user-facing line (e.g. "rate-limited"), when the
                        # provider supplied one; otherwise None.
                        "response": result.get("response"),
                        "timestamp": datetime.now().isoformat(),
                        "engine": self.engine_name,
                    }
                response = result["response"]
                source = result.get("source", mode)
                # The written reply stays detailed; the spoken version follows
                # the configured spoken_response_length.
                spoken = shorten_for_speech(response)

            return {
                "status": "success",
                "command": command,
                "response": response,
                # `spoken` is the short version MAYDAY says out loud; `response`
                # stays detailed for the on-screen panel.
                "spoken": spoken or response,
                "mode": mode,
                "source": source,
                "timestamp": datetime.now().isoformat(),
                "engine": self.engine_name,
            }

        except Exception as exc:
            logger.exception("Error processing command")
            return {
                "status": "error",
                "command": command,
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
                "engine": self.engine_name,
            }

    def _conversation_messages(self, command, limit=HISTORY_EXCHANGES):
        """Replay recent conversation so follow-up requests keep their context."""
        messages = []

        try:
            memories = get_recent_memories(limit)
        except Exception as exc:  # noqa: BLE001 - history is best-effort
            logger.warning("Could not load conversation history: %s", exc)
            memories = []

        for memory in memories:
            if not isinstance(memory, dict):
                continue

            user = str(memory.get("user_input") or "").strip()
            assistant = str(memory.get("ai_response") or "").strip()

            if user:
                messages.append({"role": "user", "content": user})
            if assistant:
                messages.append({"role": "assistant", "content": assistant})

        messages.append({"role": "user", "content": command})
        return messages

    @staticmethod
    def _format_history(messages):
        """Flatten a message list into a plain transcript for the online API."""
        lines = ["[Recent conversation]"]

        for message in messages:
            role = str(message.get("role", "user")).capitalize()
            content = str(message.get("content", "")).strip()

            if content:
                lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _generate_ai_response(self, command, params, mode):
        # The personality layer supplies MAYDAY's character; callers may still
        # override the prompt through params.
        system_prompt = params.get("system_prompt") or build_system_prompt()
        messages = params.get("messages") or self._conversation_messages(command)

        if mode == "online":
            # Gemini's Interactions API expects a text prompt, so the recent
            # conversation is folded into the prompt instead of a message list.
            return generate_online_response(
                self._format_history(messages),
                system_prompt=system_prompt,
                messages=None,
            )

        # Offline mode uses the existing Ollama service.
        return chat_with_ollama(messages, system_prompt=system_prompt)

    def _is_greeting(self, command):
        greetings = ["hello", "hi", "hey", "greetings", "what's up", "are you there"]
        return any(
            command == greeting or command.startswith(greeting + " ")
            for greeting in greetings
        )

    def _handle_greeting(self, command):
        if "are you there" in command:
            return "Always here. What are we getting into today?"
        return "Hello. I'm MAYDAY. Always here - what are we getting into today?"

    def _is_status_request(self, command):
        keywords = ["status", "how are you", "are you alive", "system status"]
        return any(keyword in command for keyword in keywords)

    def _handle_status_request(self):
        voice = get_voice_mode_status()
        online = get_online_status()
        ollama = get_ollama_status()

        return "\n".join([
            "MAYDAY STATUS",
            "• System: ONLINE",
            "• AI engine: ACTIVE",
            f"• Voice mode: {voice.get('active_mode', 'unknown')}",
            (
                "• Online AI: "
                f"{'configured' if online.get('configured') else 'not configured'}"
                f" ({online.get('provider', 'n/a')})"
            ),
            f"• Ollama: {ollama.get('status', 'unknown')}",
        ])

    def _handle_status_spoken(self):
        voice = get_voice_mode_status()
        return (
            f"All systems online. I'm running in {voice.get('active_mode', 'unknown')} "
            "mode and ready when you are."
        )

    def _is_help_request(self, command):
        keywords = ["help", "commands", "what can you do", "capabilities"]
        return any(keyword in command for keyword in keywords)

    def _handle_help_request(self):
        return (
            "Here is what I can do:\n"
            "• hello / hi - greet me\n"
            "• status - show system status\n"
            "• time - show the current date and time\n"
            "• open <app> - launch an app (notepad, chrome, explorer, cmd)\n"
            "• open <site> - open a website (youtube, google, github)\n"
            "• screenshot - capture the screen\n"
            "• show processes / system info - inspect this PC\n"
            "• lock / sleep / shutdown / restart - power controls\n"
            "• or just talk to me in natural language."
        )

    def _handle_help_spoken(self):
        return (
            "I can open apps and websites, check your system, take screenshots, "
            "and handle power controls. Or just talk to me naturally. "
            "What would you like?"
        )

    def _is_time_request(self, command):
        keywords = ["time", "what time", "current time", "what's the time"]
        return any(keyword in command for keyword in keywords)

    def _handle_time_request(self):
        now = datetime.now()
        return now.strftime(
            "It is %I:%M %p on %A, %B %d, %Y."
        )

    def _add_to_history(self, entry):
        self.command_history.append(entry)
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

    def get_history(self, limit=10):
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 10
        return self.command_history[-limit:]

    def clear_history(self):
        self.command_history = []
        logger.info("Command history cleared")

    def get_status(self):
        return {
            "engine": self.engine_name,
            "status": "ACTIVE" if self.is_active else "INACTIVE",
            "active_voice_mode": get_active_voice_mode(),
            "history_count": len(self.command_history),
            "timestamp": datetime.now().isoformat(),
        }


ai_engine = AIEngine()


def process_ai_command(command, params=None):
    return ai_engine.process_command(command, params)


def get_ai_status():
    return ai_engine.get_status()


def get_command_history(limit=10):
    return ai_engine.get_history(limit)


def clear_command_history():
    ai_engine.clear_history()
    return {"status": "success", "message": "History cleared"}
