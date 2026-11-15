# ============================================================================
# MAYDAY OS - ONLINE SERVICE
# File: backend/online_service.py
# Purpose: Gemini-powered online AI service.
# ============================================================================

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

logger = logging.getLogger(__name__)

# Always load the .env file located beside the backend code.
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)


class OnlineService:
    """
    Gemini API adapter used by MAYDAY's online mode.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv(
            "GEMINI_MODEL",
            "gemini-3.7-flash",
        ).strip()

        self.client = None
        self.last_response_time = 0.0

        if self._configured():
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Gemini online service initialized")
            except Exception as exc:
                logger.error(
                    "Failed to initialize Gemini client: %s",
                    exc,
                )

    def _configured(self):
        return bool(self.api_key) and self.api_key.lower() not in {
            "your_key_here",
            "your-api-key",
            "your_gemini_key_here",
        }

    def get_status(self):
        return {
            "configured": self._configured(),
            "provider": "gemini",
            "model": self.model,
            "timestamp": datetime.now().isoformat(),
        }

    def generate_response(
        self,
        prompt,
        system_prompt=None,
        messages=None,
    ):
        """
        Generate an online AI response using Gemini.
        """

        if not self._configured():
            return {
                "status": "error",
                "message": "GEMINI_API_KEY is not configured",
                "response": None,
                "source": "gemini",
            }

        if self.client is None:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Gemini initialization failed: {exc}",
                    "response": None,
                    "source": "gemini",
                }

        if not prompt and not messages:
            return {
                "status": "error",
                "message": "No prompt provided",
                "response": None,
                "source": "gemini",
            }

        contents = []

        if messages:
            for message in messages:
                role = message.get("role", "user")
                content = message.get("content", "")

                if not content:
                    continue

                if role == "assistant":
                    contents.append(
                        {
                            "role": "model",
                            "parts": [{"text": content}],
                        }
                    )
                else:
                    contents.append(
                        {
                            "role": "user",
                            "parts": [{"text": content}],
                        }
                    )
        else:
            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            )

        config = {}

        if system_prompt:
            config["system_instruction"] = system_prompt

        start = time.perf_counter()

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            self.last_response_time = time.perf_counter() - start

            text = ""

            if response.text:
                text = response.text.strip()

            if not text:
                return {
                    "status": "error",
                    "message": "Gemini returned an empty response",
                    "response": None,
                    "source": "gemini",
                    "response_time": self.last_response_time,
                }

            return {
                "status": "success",
                "response": text,
                "model": self.model,
                "response_time": self.last_response_time,
                "source": "gemini",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            self.last_response_time = time.perf_counter() - start

            logger.exception(
                "Gemini online AI request failed"
            )

            return {
                "status": "error",
                "message": str(exc),
                "response": None,
                "source": "gemini",
                "response_time": self.last_response_time,
            }


online_service = OnlineService()


def get_online_status():
    return online_service.get_status()


def generate_online_response(
    prompt,
    system_prompt=None,
    messages=None,
):
    return online_service.generate_response(
        prompt,
        system_prompt,
        messages,
    )