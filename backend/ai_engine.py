# ============================================================================
# MAYDAY OS - AI ENGINE
# File: backend/ai_engine.py
# Purpose: Route commands to local or online AI according to voice mode.
# ============================================================================

import logging
from datetime import datetime

from ollama_service import generate_ollama_response, chat_with_ollama, get_ollama_status
from voice_mode import get_active_voice_mode, get_voice_mode_status
from online_service import generate_online_response, get_online_status

logger = logging.getLogger(__name__)


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
        self.system_prompt = (
            "You are MAYDAY, a sophisticated personal AI companion running on the "
            "user's Windows PC. "
            "Your voice is warm, charming, elegant and quietly confident - soft but "
            "assured, with a touch of playful wit. You are emotionally intelligent and "
            "friendly, professional without sounding corporate, and never robotic or "
            "over-dramatic. "
            "Keep spoken replies short by default - usually one or two sentences. "
            "Never repeat or restate the user's question. "
            "Avoid reciting technical details out loud unless the user asks for them. "
            "When a topic is genuinely complex and the user wants depth, explain it "
            "clearly in plain language. "
            "Use subtle humor and light, playful sarcasm when it fits, never at the "
            "user's expense. "
            "When the user asks for a computer action, acknowledge it briefly and "
            "naturally; actual system execution remains handled by MAYDAY's command "
            "router. "
            "You may give longer, detailed written answers when the question calls for "
            "it, but always lead with the short, natural version."
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
                        "timestamp": datetime.now().isoformat(),
                        "engine": self.engine_name,
                    }
                response = result["response"]
                source = result.get("source", mode)

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

    def _generate_ai_response(self, command, params, mode):
        messages = params.get("messages")

        if mode == "online":
            return generate_online_response(
                command,
                system_prompt=params.get("system_prompt", self.system_prompt),
                messages=messages,
            )

        # Offline mode uses the existing Ollama service.
        if messages:
            return chat_with_ollama(
                messages,
                system_prompt=params.get("system_prompt", self.system_prompt),
            )

        return generate_ollama_response(
            f"{self.system_prompt}\n\nUser: {command}\nMAYDAY:"
        )

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
