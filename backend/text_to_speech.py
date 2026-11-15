# ============================================================================
# MAYDAY OS - TEXT-TO-SPEECH ENGINE (Kokoro-82M)
# File: backend/text_to_speech.py
# Purpose: Natural female voice output. Offline mode uses Kokoro-82M;
#          online mode uses the online speech API (falls back to Kokoro).
# ============================================================================

import logging
import os
import tempfile
import threading
import time
import wave
from datetime import datetime

import numpy as np

from online_service import synthesize_online_speech
from voice_mode import get_active_voice_mode, is_online_configured

logger = logging.getLogger(__name__)

try:
    import winsound

    WINSOUND_AVAILABLE = True
except ImportError:
    winsound = None
    WINSOUND_AVAILABLE = False

# Kokoro is imported lazily (it pulls in PyTorch, which is heavy).
KOKORO_AVAILABLE = None

DEFAULT_REPO = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


class TextToSpeechEngine:
    """
    Speaks text with Kokoro-82M (offline) or the online speech API.

    The Kokoro pipeline is created once and reused. Long responses are split
    into sentence-sized chunks and played back one at a time so playback can
    be stopped and never overlaps.
    """

    # Warm, expressive female voices, best first (verified against the model
    # repository at runtime - these are candidates, not hardcoded assumptions).
    PREFERRED_FEMALE_VOICES = [
        "af_heart",
        "af_bella",
        "af_nicole",
        "bf_emma",
        "af_aoede",
        "af_sarah",
        "bf_isabella",
    ]

    def __init__(self):
        self.is_speaking = False
        self.current_text = None
        self.speech_thread = None
        self.processing_mode = None

        # --- Configuration ------------------------------------------------
        self.repo_id = (os.getenv("KOKORO_REPO", DEFAULT_REPO) or DEFAULT_REPO).strip()
        self.lang_code = (os.getenv("KOKORO_LANG", "a") or "a").strip()
        self.device = (os.getenv("KOKORO_DEVICE", "cpu") or "cpu").strip()
        self.voice = (os.getenv("KOKORO_VOICE", "af_heart") or "af_heart").strip()
        self.speed = _env_float("KOKORO_SPEED", 1.0)
        self.volume = 1.0
        self.chunk_chars = _env_int("KOKORO_CHUNK_CHARS", 280)

        # pyttsx3-style rate (50-300). 150 == normal speed.
        self.rate = int(max(50, min(300, round(self.speed * 150))))

        self._pipeline = None
        self._pipeline_lock = threading.Lock()
        self._speak_guard = threading.Lock()
        self._stop_requested = False
        self._voices_cache = None

        logger.info(
            "Text-to-Speech Engine initialized (Kokoro voice=%s, lang=%s, speed=%.2f)",
            self.voice,
            self.lang_code,
            self.speed,
        )

    # ------------------------------------------------------------------
    # Kokoro lifecycle
    # ------------------------------------------------------------------
    def _load_pipeline(self):
        """Create the Kokoro pipeline once and reuse it."""
        global KOKORO_AVAILABLE

        if self._pipeline is not None:
            return self._pipeline

        with self._pipeline_lock:
            if self._pipeline is not None:
                return self._pipeline

            try:
                from kokoro import KPipeline

                KOKORO_AVAILABLE = True
            except ImportError as exc:
                KOKORO_AVAILABLE = False
                logger.error(
                    "kokoro not available - install with: pip install kokoro (%s)", exc
                )
                return None

            # Use every available CPU core so Kokoro synthesizes near
            # real-time on a CPU-only laptop.
            try:
                import torch

                threads = max(1, os.cpu_count() or 4)
                torch.set_num_threads(threads)
                logger.info("Kokoro torch threads set to %d", threads)
            except Exception as exc:
                logger.warning("Could not set torch thread count: %s", exc)

            try:
                logger.info(
                    "Loading Kokoro pipeline (lang_code=%s, device=%s)...",
                    self.lang_code,
                    self.device,
                )
                self._pipeline = KPipeline(
                    lang_code=self.lang_code,
                    repo_id=self.repo_id,
                    device=self.device,
                )
                logger.info("Kokoro pipeline loaded and cached")
            except Exception as exc:
                logger.error("Error loading Kokoro pipeline: %s", exc)
                self._pipeline = None

        return self._pipeline

    # ------------------------------------------------------------------
    # Voice discovery / selection
    # ------------------------------------------------------------------
    def _available_voices(self):
        """List the voices actually published by the model repository."""
        if self._voices_cache is not None:
            return self._voices_cache

        voices = []
        try:
            from huggingface_hub import list_repo_files

            files = list_repo_files(self.repo_id)
            voices = sorted(
                f.split("/")[-1][:-3]
                for f in files
                if f.startswith("voices/") and f.endswith(".pt")
            )
        except Exception as exc:
            logger.warning(
                "Could not list Kokoro voices from %s (%s); using candidates",
                self.repo_id,
                exc,
            )
            voices = list(self.PREFERRED_FEMALE_VOICES)

        self._voices_cache = voices
        return voices

    def _resolve_voice(self, requested):
        """Pick a voice that definitely exists in the installed model."""
        available = self._available_voices()
        requested = (requested or "").strip()

        if requested and (not available or requested in available):
            return requested

        if requested and available and requested not in available:
            logger.warning(
                "Voice '%s' is not available in %s; choosing a default",
                requested,
                self.repo_id,
            )

        for candidate in self.PREFERRED_FEMALE_VOICES:
            if not available or candidate in available:
                return candidate

        return requested or self.PREFERRED_FEMALE_VOICES[0]

    def get_available_voices(self):
        return [
            {
                "id": idx,
                "name": name,
                "gender": "female" if len(name) > 1 and name[1] == "f" else "other",
                "language": name[0] if name else "?",
            }
            for idx, name in enumerate(self._available_voices())
        ]

    def set_voice(self, voice_id):
        try:
            available = self._available_voices()

            if isinstance(voice_id, str) and voice_id.strip():
                name = voice_id.strip()
                if not available or name in available:
                    self.voice = name
                    logger.info("TTS voice set to %s", name)
                    return True
                return False

            index = int(voice_id)
            if 0 <= index < len(available):
                self.voice = available[index]
                logger.info("TTS voice set to %s", self.voice)
                return True

            return False
        except (TypeError, ValueError):
            return False
        except Exception as exc:
            logger.error("Error setting voice: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Speech controls
    # ------------------------------------------------------------------
    def set_rate(self, rate):
        try:
            rate = max(50, min(300, int(rate)))
            self.rate = rate
            self.speed = max(0.5, min(2.0, rate / 150.0))
            logger.info("TTS rate set to %s (speed %.2f)", rate, self.speed)
            return True
        except (TypeError, ValueError):
            return False
        except Exception as exc:
            logger.error("Error setting rate: %s", exc)
            return False

    def set_volume(self, volume):
        try:
            self.volume = max(0.0, min(1.0, float(volume)))
            return True
        except (TypeError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Synthesis / playback
    # ------------------------------------------------------------------
    def speak(self, text):
        text = str(text or "").strip()

        if not text:
            return {
                "status": "error",
                "message": "No text provided",
                "timestamp": datetime.now().isoformat(),
            }

        # Prevent overlapping playback.
        if not self._speak_guard.acquire(blocking=False):
            return {
                "status": "error",
                "message": "Already speaking",
                "timestamp": datetime.now().isoformat(),
            }

        try:
            self.is_speaking = True
            self._stop_requested = False
            self.current_text = text

            mode = get_active_voice_mode()
            if mode == "online" and not is_online_configured():
                logger.warning(
                    "Online TTS not configured; falling back to Kokoro (offline)"
                )
                mode = "offline"

            self.processing_mode = mode

            if mode == "online":
                return self._speak_online(text)

            return self._speak_kokoro(text)
        finally:
            self.is_speaking = False
            self._speak_guard.release()

    def _speak_kokoro(self, text):
        pipeline = self._load_pipeline()

        if pipeline is None:
            return {
                "status": "error",
                "message": "Kokoro is not available",
                "mode": "offline",
                "timestamp": datetime.now().isoformat(),
            }

        voice = self._resolve_voice(self.voice)
        chunks = self._chunk_text(text)
        played = 0

        try:
            for chunk in chunks:
                if self._stop_requested:
                    break

                for _graphemes, _phonemes, audio in pipeline(
                    chunk,
                    voice=voice,
                    speed=self.speed,
                ):
                    if self._stop_requested:
                        break

                    audio = np.asarray(audio, dtype=np.float32)
                    if audio.size == 0:
                        continue

                    if self.volume != 1.0:
                        audio = audio * self.volume

                    self._play_audio(audio)
                    played += 1

            return {
                "status": "success",
                "message": "Speech completed" if played else "Nothing to speak",
                "text_length": len(text),
                "chunks": len(chunks),
                "played": played,
                "mode": "offline",
                "voice": voice,
                "speed": self.speed,
                "stopped": self._stop_requested,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error("Kokoro TTS error: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "mode": "offline",
                "timestamp": datetime.now().isoformat(),
            }

    def _speak_online(self, text):
        if not WINSOUND_AVAILABLE:
            return {
                "status": "error",
                "message": "Online TTS playback currently requires Windows",
                "mode": "online",
                "timestamp": datetime.now().isoformat(),
            }

        audio_file = None

        try:
            with tempfile.NamedTemporaryFile(
                prefix="mayday_tts_",
                suffix=".wav",
                delete=False,
            ) as temp_file:
                audio_file = temp_file.name

            result = synthesize_online_speech(text, audio_file)
            if result.get("status") != "success":
                logger.warning(
                    "Online TTS failed (%s); falling back to Kokoro",
                    result.get("message", "unknown error"),
                )
                return self._speak_kokoro(text)

            winsound.PlaySound(audio_file, winsound.SND_FILENAME)

            return {
                "status": "success",
                "message": "Online speech completed",
                "text_length": len(text),
                "mode": "online",
                "model": result.get("model"),
                "voice": result.get("voice"),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error("Online TTS error: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "mode": "online",
                "timestamp": datetime.now().isoformat(),
            }
        finally:
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except OSError:
                    logger.warning("Could not remove online TTS temporary file")

    def _play_audio(self, audio):
        """Write one audio chunk to a temp WAV and play it on the speaker."""
        if not WINSOUND_AVAILABLE:
            logger.error("Playback requires Windows (winsound)")
            return

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="mayday_kokoro_",
                suffix=".wav",
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name

            self._write_wav(temp_path, audio, SAMPLE_RATE)

            duration = len(audio) / float(SAMPLE_RATE)

            # Play asynchronously so playback can be interrupted by stop.
            winsound.PlaySound(
                temp_path,
                winsound.SND_FILENAME | winsound.SND_ASYNC,
            )

            deadline = time.time() + duration + 0.05
            while time.time() < deadline:
                if self._stop_requested:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                    break
                time.sleep(0.03)

        except Exception as exc:
            logger.error("Error playing audio chunk: %s", exc)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def _write_wav(path, audio, sample_rate):
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = np.int16(clipped * 32767)
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())

    def _chunk_text(self, text):
        """Split long text into sentence-sized chunks for smooth playback."""
        text = " ".join(str(text).split())
        if len(text) <= self.chunk_chars:
            return [text] if text else []

        import re

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""

        for sentence in sentences:
            if not sentence:
                continue

            if len(sentence) > self.chunk_chars:
                # Hard-split very long sentences on word boundaries.
                if current:
                    chunks.append(current)
                    current = ""
                words = sentence.split()
                piece = ""
                for word in words:
                    if len(piece) + len(word) + 1 > self.chunk_chars:
                        chunks.append(piece)
                        piece = word
                    else:
                        piece = f"{piece} {word}".strip()
                if piece:
                    chunks.append(piece)
                continue

            if len(current) + len(sentence) + 1 > self.chunk_chars:
                if current:
                    chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()

        if current:
            chunks.append(current)

        return chunks

    def speak_async(self, text):
        if not str(text or "").strip():
            return {
                "status": "error",
                "message": "No text provided",
                "timestamp": datetime.now().isoformat(),
            }

        if self.is_speaking:
            return {
                "status": "error",
                "message": "Already speaking",
                "timestamp": datetime.now().isoformat(),
            }

        self.speech_thread = threading.Thread(
            target=self.speak,
            args=(text,),
            daemon=True,
        )
        self.speech_thread.start()

        return {
            "status": "success",
            "message": "Text to speech started",
            "mode": get_active_voice_mode(),
            "timestamp": datetime.now().isoformat(),
        }

    def stop_speaking(self):
        try:
            self._stop_requested = True

            if WINSOUND_AVAILABLE:
                winsound.PlaySound(None, winsound.SND_PURGE)

            self.is_speaking = False
            return True
        except Exception as exc:
            logger.error("Error stopping speech: %s", exc)
            return False

    def get_status(self):
        return {
            "is_speaking": self.is_speaking,
            "current_text": (
                self.current_text[:50] + "..."
                if self.current_text and len(self.current_text) > 50
                else self.current_text
            ),
            "mode": get_active_voice_mode(),
            "processing_mode": self.processing_mode,
            "engine": "kokoro",
            "kokoro_available": bool(KOKORO_AVAILABLE),
            "model_loaded": self._pipeline is not None,
            "voice": self.voice,
            "rate": self.rate,
            "speed": self.speed,
            "volume": self.volume,
            "available_voices": len(self._voices_cache) if self._voices_cache else 0,
            "sample_rate": SAMPLE_RATE,
            "playback_available": WINSOUND_AVAILABLE,
            "timestamp": datetime.now().isoformat(),
        }


tts_engine = TextToSpeechEngine()


def speak_text(text):
    return tts_engine.speak(text)


def speak_text_async(text):
    return tts_engine.speak_async(text)


def stop_speaking():
    return tts_engine.stop_speaking()


def set_voice(voice_id):
    return tts_engine.set_voice(voice_id)


def set_speech_rate(rate):
    return tts_engine.set_rate(rate)


def set_volume(volume):
    return tts_engine.set_volume(volume)


def get_voices():
    return tts_engine.get_available_voices()


def get_tts_status():
    return tts_engine.get_status()


def preload_tts_model():
    """Load the Kokoro pipeline ahead of time (background warm-up)."""
    return tts_engine._load_pipeline() is not None
