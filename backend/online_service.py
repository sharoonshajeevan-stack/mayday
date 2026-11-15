# ============================================================================
# MAYDAY OS - ONLINE SERVICE
# File: backend/online_service.py
# Purpose: Gemini-powered online AI service using the Interactions API.
# ============================================================================

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from google import genai

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


class OnlineService:
    """
    Gemini online AI service for MAYDAY.

    Uses Google's Interactions API.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()

        self.model = os.getenv(
            "GEMINI_MODEL",
            "gemini-3.6-flash",
        ).strip()

        self.client = None
        self.last_response_time = 0.0

        # OpenAI is still used for online speech-to-text and text-to-speech.
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        ).rstrip("/")
        self.stt_model = os.getenv("OPENAI_STT_MODEL", "gpt-transcribe").strip()
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
        self.tts_voice = os.getenv("OPENAI_TTS_VOICE", "onyx").strip()
        self.timeout = int(os.getenv("OPENAI_TIMEOUT", "120"))

        self.last_stt_response_time = 0.0
        self.last_tts_response_time = 0.0

        if self._configured():
            try:
                self.client = genai.Client(
                    api_key=self.api_key
                )

                logger.info(
                    "Gemini online service initialized"
                )

            except Exception as exc:
                logger.error(
                    "Gemini initialization failed: %s",
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
            "api": "interactions",
            "timestamp": datetime.now().isoformat(),
        }

    def generate_response(
        self,
        prompt,
        system_prompt=None,
        messages=None,
    ):
        """
        Generate an online AI response using Gemini Interactions API.
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
                self.client = genai.Client(
                    api_key=self.api_key
                )

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

        # Build the input for Gemini.
        if messages:
            conversation = []

            for message in messages:
                role = message.get("role", "user")
                content = message.get("content", "").strip()

                if not content:
                    continue

                if role == "assistant":
                    role = "model"

                if role == "system":
                    role = "user"

                conversation.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

            input_data = conversation

        else:
            input_data = prompt

        if system_prompt:
            system_instruction = (
                f"{system_prompt}\n\n"
                "You are operating in MAYDAY online mode. "
                "Stay in character as MAYDAY: warm, charming, and concise. "
                "Keep spoken replies short by default, and never repeat the user's "
                "question back to them."
            )

            if isinstance(input_data, str):
                input_data = (
                    f"{system_instruction}\n\n"
                    f"User: {input_data}"
                )
            else:
                input_data = [
                    {
                        "role": "user",
                        "content": system_instruction,
                    },
                    *input_data,
                ]

        start = time.perf_counter()

        try:
            interaction = self.client.interactions.create(
                model=self.model,
                input=input_data,
            )

            self.last_response_time = (
                time.perf_counter() - start
            )

            text = getattr(
                interaction,
                "output_text",
                "",
            )

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
                "response": text.strip(),
                "model": self.model,
                "response_time": self.last_response_time,
                "source": "gemini",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            self.last_response_time = (
                time.perf_counter() - start
            )

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

    # ------------------------------------------------------------------
    # Online speech-to-text and text-to-speech (OpenAI)
    # ------------------------------------------------------------------

    def _openai_configured(self):
        return bool(self.openai_api_key) and self.openai_api_key.lower() not in {
            "your_key_here",
            "your-api-key",
        }

    def _openai_headers(self):
        return {
            "Authorization": f"Bearer {self.openai_api_key}",
        }

    @staticmethod
    def _error_message(response):
        try:
            data = response.json()
            error = data.get("error", {})
            if isinstance(error, dict):
                return error.get("message") or str(error)
            return str(error)
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:300]}"

    def transcribe_audio(self, audio_file):
        """Transcribe a WAV/audio file with the online transcription API."""
        if not self._openai_configured():
            return {
                "status": "error",
                "message": "OPENAI_API_KEY is not configured",
                "transcript": "",
                "source": "openai",
            }

        if not audio_file or not os.path.exists(audio_file):
            return {
                "status": "error",
                "message": "Audio file does not exist",
                "transcript": "",
                "source": "openai",
            }

        start = time.perf_counter()
        try:
            with open(audio_file, "rb") as audio:
                response = requests.post(
                    f"{self.openai_base_url}/audio/transcriptions",
                    headers=self._openai_headers(),
                    files={
                        "file": (
                            os.path.basename(audio_file),
                            audio,
                            "audio/wav",
                        )
                    },
                    data={
                        "model": self.stt_model,
                        "language": "en",
                    },
                    timeout=self.timeout,
                )

            self.last_stt_response_time = time.perf_counter() - start

            if response.status_code != 200:
                message = self._error_message(response)
                logger.error("Online STT failed: %s", message)
                return {
                    "status": "error",
                    "message": message,
                    "transcript": "",
                    "source": "openai",
                }

            data = response.json()
            transcript = data.get("text", "").strip()

            return {
                "status": "success",
                "transcript": transcript,
                "model": self.stt_model,
                "response_time": self.last_stt_response_time,
                "source": "openai",
                "timestamp": datetime.now().isoformat(),
            }

        except requests.Timeout:
            return {
                "status": "error",
                "message": "Online STT request timed out",
                "transcript": "",
                "source": "openai",
            }
        except requests.RequestException as exc:
            logger.error("Online STT network error: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "transcript": "",
                "source": "openai",
            }
        except Exception as exc:
            logger.exception("Unexpected online STT error")
            return {
                "status": "error",
                "message": str(exc),
                "transcript": "",
                "source": "openai",
            }

    def synthesize_speech(self, text, output_file):
        """Generate WAV speech and save it locally for playback."""
        if not self._openai_configured():
            return {
                "status": "error",
                "message": "OPENAI_API_KEY is not configured",
                "audio_file": None,
                "source": "openai",
            }

        if not text or not text.strip():
            return {
                "status": "error",
                "message": "No text provided",
                "audio_file": None,
                "source": "openai",
            }

        payload = {
            "model": self.tts_model,
            "voice": self.tts_voice,
            "input": text,
            "response_format": "wav",
        }

        start = time.perf_counter()
        try:
            response = requests.post(
                f"{self.openai_base_url}/audio/speech",
                headers={
                    **self._openai_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            self.last_tts_response_time = time.perf_counter() - start

            if response.status_code != 200:
                message = self._error_message(response)
                logger.error("Online TTS failed: %s", message)
                return {
                    "status": "error",
                    "message": message,
                    "audio_file": None,
                    "source": "openai",
                }

            with open(output_file, "wb") as audio:
                audio.write(response.content)

            return {
                "status": "success",
                "audio_file": output_file,
                "model": self.tts_model,
                "voice": self.tts_voice,
                "response_time": self.last_tts_response_time,
                "source": "openai",
                "timestamp": datetime.now().isoformat(),
            }

        except requests.Timeout:
            return {
                "status": "error",
                "message": "Online TTS request timed out",
                "audio_file": None,
                "source": "openai",
            }
        except requests.RequestException as exc:
            logger.error("Online TTS network error: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "audio_file": None,
                "source": "openai",
            }
        except Exception as exc:
            logger.exception("Unexpected online TTS error")
            return {
                "status": "error",
                "message": str(exc),
                "audio_file": None,
                "source": "openai",
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


def transcribe_online_audio(audio_file):
    return online_service.transcribe_audio(audio_file)


def synthesize_online_speech(text, output_file):
    return online_service.synthesize_speech(text, output_file)