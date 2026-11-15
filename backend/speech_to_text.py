# ============================================================================
# MAYDAY OS - SPEECH-TO-TEXT ENGINE (Faster-Whisper)
# File: backend/speech_to_text.py
# Purpose: Record the microphone and transcribe with Faster-Whisper (offline)
#          or the online OpenAI transcription API (online mode).
# ============================================================================

import logging
import os
import threading
import wave
from datetime import datetime

import numpy as np
import pyaudio

from online_service import transcribe_online_audio
from voice_mode import get_active_voice_mode, is_online_configured

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None
    FASTER_WHISPER_AVAILABLE = False
    logger.warning(
        "faster-whisper not available - install with: pip install faster-whisper"
    )


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


class SpeechToTextEngine:
    """
    Records microphone audio and transcribes it.

    Offline mode -> Faster-Whisper (CPU, int8) - the model is loaded once and
                    reused for every transcription.
    Online mode  -> the online transcription API (falls back to Faster-Whisper
                    when the online key is not configured).
    """

    def __init__(self):
        self.is_recording = False
        self.audio_file = None
        self.transcript = None
        self.recording_thread = None
        self.confidence = 0.0
        self.processing_mode = None

        # --- Microphone capture settings -----------------------------------
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paFloat32
        self.CHANNELS = 1
        self.RATE = 16000
        self.SILENCE_THRESHOLD = _env_float("STT_SILENCE_THRESHOLD", 0.012)
        self.MIN_RECORDING_LENGTH = _env_float("STT_MIN_SECONDS", 0.6)
        self.MAX_RECORDING_LENGTH = _env_float("STT_MAX_SECONDS", 30.0)
        self.SILENCE_DURATION = _env_float("STT_SILENCE_SECONDS", 1.4)

        self.audio_buffer = []
        self._audio_processed = False

        # --- Faster-Whisper settings (CPU / int8 by default) ---------------
        self.model_size = (os.getenv("WHISPER_MODEL", "base") or "base").strip()
        self.device = (os.getenv("WHISPER_DEVICE", "cpu") or "cpu").strip()
        self.compute_type = (
            os.getenv("WHISPER_COMPUTE_TYPE", "int8") or "int8"
        ).strip()
        self.language = (os.getenv("WHISPER_LANGUAGE", "en") or "").strip() or None
        self.beam_size = _env_int("WHISPER_BEAM_SIZE", 1)

        # The model is created lazily and reused (never reloaded per request).
        self._model = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

        logger.info(
            "Speech-to-Text Engine initialized "
            "(faster-whisper=%s, model=%s, %s/%s)",
            FASTER_WHISPER_AVAILABLE,
            self.model_size,
            self.device,
            self.compute_type,
        )

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------
    def _load_model(self):
        """Load the Faster-Whisper model once and reuse it."""
        if not FASTER_WHISPER_AVAILABLE:
            logger.error(
                "faster-whisper is not installed; cannot transcribe offline"
            )
            return None

        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is None:
                try:
                    logger.info(
                        "Loading faster-whisper model '%s' (%s / %s)...",
                        self.model_size,
                        self.device,
                        self.compute_type,
                    )
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
                    logger.info("faster-whisper model loaded and cached")
                except Exception as exc:
                    logger.error("Error loading faster-whisper model: %s", exc)
                    self._model = None

        return self._model

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def start_recording(self):
        if self.is_recording:
            logger.warning("Already recording")
            return False

        try:
            self.is_recording = True
            self.audio_buffer = []
            self._audio_processed = False
            self.transcript = None
            self.confidence = 0.0
            self.processing_mode = get_active_voice_mode()

            self.recording_thread = threading.Thread(
                target=self._record_audio,
                daemon=True,
            )
            self.recording_thread.start()

            logger.info("Recording started (%s mode)", self.processing_mode)
            return True

        except Exception as exc:
            logger.error("Error starting recording: %s", exc)
            self.is_recording = False
            return False

    def stop_recording(self):
        """
        Stop capturing and produce the transcript.

        This is safe to call even after the recorder auto-stopped (silence or
        maximum length): the buffered audio is processed exactly once.
        """
        try:
            if self.is_recording:
                self.is_recording = False

                if self.recording_thread:
                    self.recording_thread.join(timeout=5)

            if not self._audio_processed:
                if self.audio_buffer:
                    self._process_audio()
                else:
                    self.transcript = ""
                    self.confidence = 0.0

                self._audio_processed = True

            logger.info("Recording stopped. Transcript: %s", self.transcript)
            return True

        except Exception as exc:
            logger.error("Error stopping recording: %s", exc)
            self.transcript = ""
            self.confidence = 0.0
            return False

    def _record_audio(self):
        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
            )

            recording_duration = 0.0
            silence_duration = 0.0

            while self.is_recording:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.float32)

                self.audio_buffer.append(audio_data)

                energy = float(np.sqrt(np.mean(audio_data ** 2)))
                chunk_duration = len(audio_data) / self.RATE
                recording_duration += chunk_duration

                if recording_duration >= self.MAX_RECORDING_LENGTH:
                    logger.info("Maximum recording length reached")
                    self.is_recording = False
                    break

                if energy < self.SILENCE_THRESHOLD:
                    silence_duration += chunk_duration
                else:
                    silence_duration = 0.0

                if (
                    silence_duration >= self.SILENCE_DURATION
                    and recording_duration >= self.MIN_RECORDING_LENGTH
                ):
                    logger.info("Silence detected; stopping recording")
                    self.is_recording = False
                    break

        except Exception as exc:
            logger.error("Fatal audio recording error: %s", exc)
            self.is_recording = False
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------
    def _process_audio(self):
        try:
            combined_audio = np.concatenate(self.audio_buffer).astype(
                np.float32, copy=False
            )
        except ValueError:
            self.transcript = ""
            self.confidence = 0.0
            return
        finally:
            # Release the buffer so the same audio is never processed twice.
            self.audio_buffer = []

        # Ignore clips that are too short to contain speech.
        if combined_audio.size < int(self.RATE * self.MIN_RECORDING_LENGTH):
            self.transcript = ""
            self.confidence = 0.0
            return

        mode = self.processing_mode or get_active_voice_mode()

        if mode == "online" and not is_online_configured():
            logger.warning(
                "Online STT not configured; falling back to offline Faster-Whisper"
            )
            mode = "offline"

        try:
            if mode == "online":
                self._transcribe_online(combined_audio)
            else:
                self._transcribe_local(combined_audio)
        except Exception as exc:
            logger.error("Error processing audio: %s", exc)
            self.transcript = ""
            self.confidence = 0.0

    def _transcribe_local(self, audio_array):
        """Transcribe a float32 16 kHz array with Faster-Whisper."""
        model = self._load_model()

        if model is None:
            self.transcript = ""
            self.confidence = 0.0
            return

        # Faster-Whisper only accepts one array at a time safely.
        with self._transcribe_lock:
            segments, info = model.transcribe(
                audio_array,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
            )

            collected = []
            logprobs = []

            for segment in segments:
                text = (segment.text or "").strip()
                if text:
                    collected.append(text)

                if getattr(segment, "avg_logprob", None) is not None:
                    logprobs.append(float(segment.avg_logprob))

        text = " ".join(collected).strip()

        self.transcript = text
        self.confidence = self._confidence_from_logprobs(logprobs) if text else 0.0
        logger.info(
            "Transcribed locally (%s): %r", getattr(info, "language", "?"), text
        )

    def _transcribe_online(self, audio_array):
        """Write a temporary WAV and transcribe it with the online API."""
        temp_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "temp_audio.wav",
        )

        try:
            self._save_audio_file(audio_array, temp_file)
            result = transcribe_online_audio(temp_file)

            if result.get("status") == "success":
                self.transcript = (result.get("transcript") or "").strip()
                self.confidence = 1.0 if self.transcript else 0.0
            else:
                logger.warning(
                    "Online STT failed (%s); falling back to Faster-Whisper",
                    result.get("message", "unknown error"),
                )
                self._transcribe_local(audio_array)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    logger.warning("Could not remove temporary audio file")

    @staticmethod
    def _confidence_from_logprobs(logprobs):
        if not logprobs:
            return 0.0
        average = sum(logprobs) / len(logprobs)
        return max(0.0, min(1.0, float(np.exp(average))))

    def _save_audio_file(self, audio_data, filename):
        with wave.open(filename, "wb") as wav_file:
            wav_file.setnchannels(self.CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.RATE)

            clipped = np.clip(audio_data, -1.0, 1.0)
            audio_int16 = np.int16(clipped * 32767)
            wav_file.writeframes(audio_int16.tobytes())

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def get_transcript(self):
        return {
            "transcript": self.transcript,
            "confidence": self.confidence,
            "mode": self.processing_mode,
            "timestamp": datetime.now().isoformat(),
        }

    def get_status(self):
        return {
            "is_recording": self.is_recording,
            "status": "recording" if self.is_recording else "idle",
            "faster_whisper_available": FASTER_WHISPER_AVAILABLE,
            "model_loaded": self._model is not None,
            "model": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type,
            "mode": get_active_voice_mode(),
            "processing_mode": self.processing_mode,
            "timestamp": datetime.now().isoformat(),
        }

    def clear_transcript(self):
        self.transcript = None
        self.confidence = 0.0
        self.processing_mode = None


stt_engine = SpeechToTextEngine()


def start_recording():
    return stt_engine.start_recording()


def stop_recording():
    result = stt_engine.stop_recording()
    if result:
        return stt_engine.get_transcript()
    return {"error": "Failed to stop recording"}


def get_stt_status():
    return stt_engine.get_status()


def get_stt_transcript():
    return stt_engine.get_transcript()


def clear_stt_transcript():
    stt_engine.clear_transcript()
    return {"status": "success", "message": "Transcript cleared"}


def preload_stt_model():
    """Load the Faster-Whisper model ahead of time (background warm-up)."""
    return stt_engine._load_model() is not None
