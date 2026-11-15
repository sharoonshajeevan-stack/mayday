# ============================================================================
# MAYDAY OS - OLLAMA SERVICE
# File: backend/ollama_service.py
# Purpose: Connect MAYDAY to Ollama for offline AI responses
# ============================================================================

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv


# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_FILE)

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"


# ============================================================================
# OLLAMA SERVICE CLASS
# ============================================================================

class OllamaService:
    """
    MAYDAY local Ollama service.

    Handles:
    - Ollama availability checks
    - Local model discovery
    - Offline AI generation
    - Conversation-based Ollama chat
    """

    def __init__(self, host=None, model=None):
        env_host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).strip()
        env_model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()

        self.host = (host or env_host or DEFAULT_OLLAMA_HOST).rstrip("/")
        self.model = model or env_model or DEFAULT_OLLAMA_MODEL

        self.is_available = False
        self.response_time = 0.0

        self._check_availability()

        logger.info(
            "Ollama Service initialized (Host: %s, Model: %s)",
            self.host,
            self.model,
        )

    # ========================================================================
    # AVAILABILITY
    # ========================================================================

    def _check_availability(self):
        """Check whether the local Ollama server is running."""

        try:
            response = requests.get(
                f"{self.host}/api/tags",
                timeout=2,
            )

            self.is_available = response.status_code == 200

            if self.is_available:
                logger.info("Ollama server is running")
            else:
                logger.warning(
                    "Ollama server returned HTTP %s",
                    response.status_code,
                )

        except requests.RequestException as exc:
            logger.warning("Ollama not available: %s", exc)
            self.is_available = False

        except Exception as exc:
            logger.error(
                "Unexpected Ollama availability error: %s",
                exc,
            )
            self.is_available = False

        return self.is_available

    # ========================================================================
    # STATUS
    # ========================================================================

    def get_status(self):
        """Get current Ollama service status."""

        self._check_availability()

        return {
            "available": self.is_available,
            "host": self.host,
            "model": self.model,
            "status": "ONLINE" if self.is_available else "OFFLINE",
            "response_time": self.response_time,
            "timestamp": datetime.now().isoformat(),
        }

    # ========================================================================
    # MODEL DISCOVERY
    # ========================================================================

    def get_available_models(self):
        """Return locally installed Ollama models."""

        try:
            if not self._check_availability():
                return {
                    "status": "error",
                    "message": "Ollama not available",
                    "models": [],
                }

            response = requests.get(
                f"{self.host}/api/tags",
                timeout=5,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": (
                        f"Failed to get models: HTTP "
                        f"{response.status_code}"
                    ),
                    "models": [],
                }

            data = response.json()
            models = []

            for model in data.get("models", []):
                models.append({
                    "name": model.get("name", "unknown"),
                    "size": model.get("size", 0),
                    "modified": model.get("modified_at", ""),
                })

            logger.info(
                "Found %d Ollama model(s)",
                len(models),
            )

            return {
                "status": "success",
                "models": models,
                "count": len(models),
            }

        except requests.RequestException as exc:
            logger.error(
                "Error getting Ollama models: %s",
                exc,
            )

            return {
                "status": "error",
                "message": str(exc),
                "models": [],
            }

        except Exception as exc:
            logger.exception(
                "Unexpected error getting Ollama models"
            )

            return {
                "status": "error",
                "message": str(exc),
                "models": [],
            }

    # ========================================================================
    # RESPONSE GENERATION
    # ========================================================================

    def generate_response(self, prompt, stream=False):
        """
        Generate an offline response using Ollama.
        """

        if not prompt or not str(prompt).strip():
            return {
                "status": "error",
                "message": "No prompt provided",
                "response": None,
                "source": "ollama",
            }

        if not self.is_available:
            self._check_availability()

        if not self.is_available:
            return {
                "status": "error",
                "message": "Ollama not available",
                "response": None,
                "source": "ollama",
            }

        try:
            logger.info(
                "Generating response with %s...",
                self.model,
            )

            payload = {
                "model": self.model,
                "prompt": str(prompt),
                "stream": False,
            }

            start_time = datetime.now()

            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=120,
            )

            self.response_time = (
                datetime.now() - start_time
            ).total_seconds()

            if response.status_code != 200:
                logger.error(
                    "Ollama returned HTTP %s",
                    response.status_code,
                )

                return {
                    "status": "error",
                    "message": (
                        f"Ollama returned "
                        f"{response.status_code}"
                    ),
                    "response": None,
                    "source": "ollama",
                    "response_time": self.response_time,
                }

            data = response.json()
            result_text = data.get("response", "").strip()

            logger.info(
                "Ollama response generated in %.2fs",
                self.response_time,
            )

            return {
                "status": "success",
                "response": result_text,
                "model": self.model,
                "response_time": self.response_time,
                "source": "ollama",
                "timestamp": datetime.now().isoformat(),
            }

        except requests.Timeout:
            logger.error("Ollama request timed out")

            return {
                "status": "error",
                "message": "Ollama request timed out",
                "response": None,
                "source": "ollama",
            }

        except requests.RequestException as exc:
            logger.error(
                "Ollama network error: %s",
                exc,
            )

            self.is_available = False

            return {
                "status": "error",
                "message": str(exc),
                "response": None,
                "source": "ollama",
            }

        except Exception as exc:
            logger.exception(
                "Unexpected Ollama response error"
            )

            return {
                "status": "error",
                "message": str(exc),
                "response": None,
                "source": "ollama",
            }

    # ========================================================================
    # CONVERSATION CHAT
    # ========================================================================

    def chat(self, messages, system_prompt=None):
        """
        Generate an Ollama response using conversation history.
        """

        try:
            if not messages:
                return {
                    "status": "error",
                    "message": "No messages provided",
                    "response": None,
                    "source": "ollama",
                }

            prompt_parts = []

            if system_prompt:
                prompt_parts.append(
                    f"System: {system_prompt}"
                )

            for message in messages:
                role = str(
                    message.get("role", "user")
                ).capitalize()

                content = str(
                    message.get("content", "")
                ).strip()

                if content:
                    prompt_parts.append(
                        f"{role}: {content}"
                    )

            prompt_parts.append("Assistant:")

            prompt = "\n\n".join(prompt_parts)

            return self.generate_response(prompt)

        except Exception as exc:
            logger.exception(
                "Error in Ollama conversation chat"
            )

            return {
                "status": "error",
                "message": str(exc),
                "response": None,
                "source": "ollama",
            }

    # ========================================================================
    # MODEL SELECTION
    # ========================================================================

    def set_model(self, model_name):
        """Change MAYDAY's active local Ollama model."""

        model_name = str(model_name or "").strip()

        if not model_name:
            return {
                "status": "error",
                "message": "Model name cannot be empty",
            }

        self.model = model_name

        logger.info(
            "Ollama model changed to: %s",
            model_name,
        )

        return {
            "status": "success",
            "model": model_name,
        }


# ============================================================================
# GLOBAL OLLAMA INSTANCE
# ============================================================================

ollama_service = OllamaService()


# ============================================================================
# PUBLIC FUNCTIONS
# ============================================================================

def get_ollama_status():
    """Get Ollama service status."""

    return ollama_service.get_status()


def get_ollama_models():
    """Get locally available Ollama models."""

    return ollama_service.get_available_models()


def generate_ollama_response(prompt):
    """Generate an offline Ollama response."""

    return ollama_service.generate_response(prompt)


def chat_with_ollama(messages, system_prompt=None):
    """Chat with Ollama using conversation history."""

    return ollama_service.chat(
        messages,
        system_prompt,
    )


def set_ollama_model(model_name):
    """Set the active Ollama model."""

    return ollama_service.set_model(model_name)