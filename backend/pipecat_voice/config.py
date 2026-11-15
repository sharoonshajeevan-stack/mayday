# ============================================================================
# MAYDAY OS - REAL-TIME VOICE CONFIGURATION
# File: backend/pipecat_voice/config.py
# Purpose: All tunables for the real-time voice service, read from the
#          environment so nothing is hard-coded.
# ============================================================================

import os
from dataclasses import dataclass


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return int(default)


def _env_optional_int(name):
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _env_float(name, default):
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return float(default)


def _env_str(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


@dataclass
class VoiceServiceConfig:
    """Configuration for the real-time Pipecat voice service."""

    # --- Service binding --------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 7860
    # Optional shared token. When set, control clients must pass ?token=...
    token: str = ""
    # "local" = the service drives the machine's own microphone + speakers
    # (the setup MAYDAY already uses). Reserved for future transports.
    transport: str = "local"
    # Start listening as soon as the service boots (otherwise the front-end
    # asks for it explicitly).
    autostart: bool = False
    log_level: str = "INFO"

    # --- Audio devices ----------------------------------------------------
    audio_in_sample_rate: int = 16000
    audio_out_sample_rate: int = 24000
    input_device_index: int | None = None
    output_device_index: int | None = None

    # --- Voice activity detection ----------------------------------------
    # confidence: Silero VAD speech probability threshold (0-1).
    # start_secs: how long speech must last before it counts as speech.
    # stop_secs:  how long silence must last before the user is "done".
    # min_volume: minimum RMS volume for a frame to be considered speech.
    vad_confidence: float = 0.6
    vad_start_secs: float = 0.2
    vad_stop_secs: float = 0.8
    vad_min_volume: float = 0.6

    # How long to wait, after the user stops, before forcing the turn closed.
    user_turn_stop_timeout: float = 4.0

    # Extra silence the segmented STT keeps after speech stops.
    stt_trailing_silence_secs: float = 0.4

    @classmethod
    def from_env(cls):
        return cls(
            host=_env_str("MAYDAY_VOICE_HOST", "127.0.0.1"),
            port=_env_int("MAYDAY_VOICE_PORT", 7860),
            token=_env_str("MAYDAY_VOICE_TOKEN", ""),
            transport=_env_str("MAYDAY_VOICE_TRANSPORT", "local").lower(),
            autostart=_env_bool("MAYDAY_VOICE_AUTOSTART", False),
            log_level=_env_str("MAYDAY_VOICE_LOG_LEVEL", "INFO").upper(),
            audio_in_sample_rate=_env_int("MAYDAY_VOICE_IN_RATE", 16000),
            audio_out_sample_rate=_env_int("MAYDAY_VOICE_OUT_RATE", 24000),
            input_device_index=_env_optional_int("MAYDAY_VOICE_INPUT_DEVICE"),
            output_device_index=_env_optional_int("MAYDAY_VOICE_OUTPUT_DEVICE"),
            vad_confidence=_env_float("MAYDAY_VAD_CONFIDENCE", 0.6),
            vad_start_secs=_env_float("MAYDAY_VAD_START_SECS", 0.2),
            vad_stop_secs=_env_float("MAYDAY_VAD_STOP_SECS", 0.8),
            vad_min_volume=_env_float("MAYDAY_VAD_MIN_VOLUME", 0.6),
            user_turn_stop_timeout=_env_float("MAYDAY_USER_TURN_STOP_TIMEOUT", 4.0),
            stt_trailing_silence_secs=_env_float("MAYDAY_STT_TRAILING_SILENCE", 0.4),
        )

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"
