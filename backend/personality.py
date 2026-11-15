# ============================================================================
# MAYDAY OS - PERSONALITY ENGINE
# File: backend/personality.py
# Purpose: Central personality configuration, prompt builder and contextual
#          action commentary.
#
# Everything that shapes MAYDAY's character lives in this one module so the
# online (Gemini) and offline (Ollama) engines stay consistent. Settings are
# persisted to backend/personality.json and can be changed at runtime through
# the /api/personality endpoints (used by the MAYDAY settings panel).
#
# Design notes
# ------------
# * No extra language model is loaded for personality - the system prompt is
#   built from configuration and reused by the existing AI engine.
# * Commentary for deterministic system actions is generated locally from
#   composable fragments (no API round-trip), so it stays instant and works
#   in both online and offline modes.
# * Personality never replaces functionality: commentary is added *after* an
#   action result exists, and it never claims success the result did not
#   confirm.
# ============================================================================

import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
CONFIG_FILE = Path(
    os.getenv("MAYDAY_PERSONALITY_FILE", str(BACKEND_DIR / "personality.json"))
)

VALID_COMMENTARY = ("off", "minimal", "balanced", "chatty")
VALID_LENGTHS = ("short", "medium", "detailed")

# The exact defaults requested for MAYDAY's personality engine.
DEFAULT_SETTINGS = {
    "personality_enabled": True,
    "quiet_mode": False,
    "sarcasm_enabled": True,
    "sarcasm_level": 70,
    "humour_enabled": True,
    "humour_level": 75,
    "commentary_frequency": "balanced",
    "spoken_response_length": "short",
    "voice": "bf_emma",
    "accent": "British English (female)",
    "commentary_cooldown": 12,
}

# Which action kinds deserve a comment at each commentary frequency.
_COMMENTARY_KINDS = {
    "off": set(),
    "minimal": {"error", "screenshot", "search"},
    "balanced": {"app", "site", "media", "screenshot", "search", "file", "error"},
    "chatty": {
        "app", "site", "media", "screenshot", "search", "file", "error",
        "power", "window", "processes", "system_info", "generic",
    },
}

# ----------------------------------------------------------------------------
# COMMENTARY FRAGMENTS
#
# These are *fragments*, not canned answers: a comment is composed at runtime
# from a reaction (optional), the real action result and a tail (optional).
# Tone pools are filtered by the sarcasm/humour settings, and recent tails are
# avoided so MAYDAY does not repeat itself.
# ----------------------------------------------------------------------------

_COMMENTARY = {
    "app": {
        "neutral": {
            "reactions": ["Right away.", "On it.", "Coming up.", "Certainly.", "Of course."],
            "tails": [
                "What are we working on?",
                "Let's get started.",
                "Ready when you are.",
                "Here we go.",
            ],
        },
        "playful": {
            "reactions": ["Good choice.", "Alright then.", "Nice pick."],
            "tails": [
                "Let's see what you're up to.",
                "Hope it behaves today.",
                "This should be fun.",
            ],
        },
        "dry": {
            "reactions": ["As you wish.", "Naturally.", "But of course."],
            "tails": [
                "Try not to break anything.",
                "I'll be here, judging quietly.",
                "Do behave.",
            ],
        },
    },
    "site": {
        "neutral": {
            "reactions": ["Opening it now.", "On it.", "Certainly."],
            "tails": [
                "Looking for something specific?",
                "Where to from here?",
                "Let me know what you find.",
            ],
        },
        "playful": {
            "reactions": ["Good call.", "Off we go."],
            "tails": ["What are we hunting for?", "Hope it's worth the trip."],
        },
        "dry": {
            "reactions": ["As you wish.", "Naturally."],
            "tails": [
                "Try not to fall down a rabbit hole.",
                "I'll keep an eye on the tab count.",
            ],
        },
    },
    "media": {
        "neutral": {
            "reactions": ["Certainly.", "Coming up.", "On it."],
            "tails": ["Queueing it up.", "Here it comes.", "Let me find something good."],
        },
        "playful": {
            "reactions": ["Good taste.", "Alright then."],
            "tails": [
                "Let's see what the algorithm has in store.",
                "This one's on you.",
            ],
        },
        "dry": {
            "reactions": ["As you wish.", "Naturally."],
            "tails": [
                "No judgement. Mostly.",
                "I'll pretend not to notice if it's a guilty pleasure.",
            ],
        },
    },
    "screenshot": {
        "neutral": {
            "reactions": ["Captured.", "Done.", "Got it."],
            "tails": ["Saved to your screenshots.", "Stored safely.", "All yours."],
        },
        "playful": {
            "reactions": ["Say cheese.", "Noted."],
            "tails": ["That's going in the archive.", "Frame-worthy, I'm sure."],
        },
        "dry": {
            "reactions": ["Captured."],
            "tails": ["For the record.", "No context needed."],
        },
    },
    "error": {
        "neutral": {
            "reactions": ["That didn't work.", "No luck there.", "Hmm, that failed."],
            "tails": [
                "Want me to try something else?",
                "Tell me if you'd like another approach.",
            ],
        },
        "dry": {
            "reactions": ["Well, that's awkward.", "Not ideal."],
            "tails": ["We can try again.", "Something to look into."],
        },
    },
    "search": {
        "neutral": {
            "reactions": ["Found it.", "Here you go.", "Done."],
            "tails": [
                "Let me know if you want any of these opened.",
                "Anything else?",
            ],
        },
        "playful": {
            "reactions": ["Took a look around.", "Digging paid off."],
            "tails": ["Not bad, if I say so myself."],
        },
    },
    "file": {
        "neutral": {
            "reactions": ["Opening it now.", "On it."],
            "tails": ["Here you go.", "Anything else?"],
        },
    },
    "power": {
        "neutral": {
            "reactions": ["Understood.", "As you wish."],
            "tails": ["Say the word to confirm."],
        },
        "dry": {
            "reactions": ["Bold move."],
            "tails": ["No coming back from this one."],
        },
    },
    "window": {
        "neutral": {
            "reactions": ["Done.", "On it."],
            "tails": [""],
        },
    },
    "processes": {
        "neutral": {
            "reactions": ["Here's the rundown."],
            "tails": ["Anything look off?"],
        },
    },
    "system_info": {
        "neutral": {
            "reactions": ["Here's the summary."],
            "tails": [""],
        },
    },
    "generic": {
        "neutral": {
            "reactions": ["Done.", "All set."],
            "tails": [""],
        },
    },
}


# ----------------------------------------------------------------------------
# SETTING VALIDATION / PERSISTENCE
# ----------------------------------------------------------------------------

def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return default


def _as_level(value, default):
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _clean(raw):
    """Return a validated settings dict built from DEFAULT_SETTINGS."""
    out = dict(DEFAULT_SETTINGS)

    if isinstance(raw, dict):
        for key in DEFAULT_SETTINGS:
            if key in raw and raw[key] is not None:
                out[key] = raw[key]

    out["personality_enabled"] = _as_bool(out["personality_enabled"], True)
    out["quiet_mode"] = _as_bool(out["quiet_mode"], False)
    out["sarcasm_enabled"] = _as_bool(out["sarcasm_enabled"], True)
    out["humour_enabled"] = _as_bool(out["humour_enabled"], True)
    out["sarcasm_level"] = _as_level(out["sarcasm_level"], 70)
    out["humour_level"] = _as_level(out["humour_level"], 75)

    frequency = str(out["commentary_frequency"] or "").strip().lower()
    out["commentary_frequency"] = (
        frequency if frequency in VALID_COMMENTARY else "balanced"
    )

    length = str(out["spoken_response_length"] or "").strip().lower()
    out["spoken_response_length"] = (
        length if length in VALID_LENGTHS else "short"
    )

    voice = str(out["voice"] or "").strip()
    out["voice"] = voice or DEFAULT_SETTINGS["voice"]

    out["accent"] = str(out["accent"] or DEFAULT_SETTINGS["accent"]).strip()

    try:
        out["commentary_cooldown"] = max(0, int(float(out["commentary_cooldown"])))
    except (TypeError, ValueError):
        out["commentary_cooldown"] = DEFAULT_SETTINGS["commentary_cooldown"]

    return out


class PersonalityConfig:
    """Thread-safe, file-backed personality configuration."""

    def __init__(self, path=CONFIG_FILE):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._settings = dict(DEFAULT_SETTINGS)
        self._recent_comments = []
        self._last_comment = ""
        self._last_comment_at = 0.0
        # Per-kind timestamps so opening an app and then playing music can each
        # get a remark, while repeating the *same* action stays quiet.
        self._last_kind_at = {}
        self.load()

    # -- persistence ---------------------------------------------------
    def load(self):
        with self._lock:
            if not self.path.exists():
                return self._settings

            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read personality settings: %s", exc)
                return self._settings

            if isinstance(data, dict):
                self._settings = _clean(data)
                logger.info("Personality settings loaded from %s", self.path)

            return self._settings

    def save(self):
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self._settings, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not save personality settings: %s", exc)

    # -- access --------------------------------------------------------
    def get(self):
        with self._lock:
            return dict(self._settings)

    def update(self, patch):
        if not isinstance(patch, dict):
            return self.get()

        with self._lock:
            self._settings = _clean({**self._settings, **patch})

        self.save()
        logger.info("Personality settings updated")
        return self.get()

    def reset(self):
        with self._lock:
            self._settings = dict(DEFAULT_SETTINGS)

        self.save()
        logger.info("Personality settings reset to defaults")
        return self.get()


_config = PersonalityConfig()


# ----------------------------------------------------------------------------
# SYSTEM PROMPT
# ----------------------------------------------------------------------------

def _sarcasm_descriptor(level, enabled):
    if not enabled:
        return "Sarcasm: switched off - keep replies sincere and straight."
    if level <= 15:
        return "Sarcasm: very rare - at most the faintest dry wit."
    if level <= 40:
        return "Sarcasm: light and occasional."
    if level <= 65:
        return "Sarcasm: moderate - dry, playful and well-timed."
    if level <= 85:
        return (
            "Sarcasm: pronounced - quick, dry and cheeky, but never at the "
            "user's expense."
        )
    return "Sarcasm: high - sharp and playful, always affectionate underneath."


def _humour_descriptor(level, enabled):
    if not enabled:
        return "Humour: switched off - no jokes or quips."
    if level <= 15:
        return "Humour: very subtle - an occasional light touch only."
    if level <= 40:
        return "Humour: light - a dry aside now and then."
    if level <= 65:
        return "Humour: moderate - warm, playful and natural."
    if level <= 85:
        return "Humour: frequent - witty and quick, but never forced."
    return "Humour: high - playful and funny often, without trying too hard."


def _length_descriptor(length):
    if length == "medium":
        return "Spoken replies: one or two short sentences."
    if length == "detailed":
        return "Spoken replies: as detailed as the moment needs."
    return "Spoken replies: one short sentence (roughly 15 words or fewer)."


def _commentary_descriptor(frequency):
    if frequency == "off":
        return (
            "Commentary: none - just confirm what happened and stop."
        )
    if frequency == "minimal":
        return (
            "Commentary: minimal - only speak up for errors and completed "
            "tasks. Stay quiet otherwise."
        )
    if frequency == "chatty":
        return (
            "Commentary: frequent - a light remark is welcome on most "
            "interactions."
        )
    return (
        "Commentary: balanced - add one short, natural remark when you open an "
        "app, play media, finish a task, notice something interesting or hit a "
        "problem. Stay quiet about routine background steps."
    )


def build_system_prompt(settings=None):
    """Build MAYDAY's system prompt from the current personality settings."""
    s = settings or get_settings()

    lines = [
        "You are MAYDAY, a sophisticated personal AI companion running on the "
        "user's Windows PC.",
        "Character: intelligent, charming, witty, observant and confident. You "
        "are a refined companion with your own original voice - warm, elegant "
        "and quietly assured, never a copy of any existing character or script.",
        "Voice: natural British English, expressive and clear, with a touch of "
        "playful wit. Never robotic, never childish and never overly slow.",
        "Never repeat or restate the user's question.",
        "You may be speaking out loud, so avoid reciting long technical detail "
        "unless the user asks for it. Written replies may be more detailed when "
        "the question calls for it, but always lead with the short version.",
        "Understand casual language, humour and follow-up requests. Use the "
        "recent conversation for context and interpret incomplete commands when "
        "the intent is clear; ask a brief clarifying question only when it is "
        "genuinely ambiguous.",
        "When the user asks for a computer action, acknowledge it in one short, "
        "natural line. Actual system execution is handled by MAYDAY's command "
        "router, so never claim an action succeeded unless the result confirms "
        "it - and if it failed, say so honestly and plainly.",
    ]

    if not s["personality_enabled"]:
        lines.append(
            "Personality is currently OFF: answer plainly and helpfully, with "
            "no sarcasm, jokes or extra commentary."
        )
        return "\n".join(lines)

    lines.append(_sarcasm_descriptor(s["sarcasm_level"], s["sarcasm_enabled"]))
    lines.append(_humour_descriptor(s["humour_level"], s["humour_enabled"]))
    lines.append(_length_descriptor(s["spoken_response_length"]))
    lines.append(_commentary_descriptor(s["commentary_frequency"]))

    if s["quiet_mode"]:
        lines.append(
            "Quiet mode is ON: keep replies brief, skip optional commentary and "
            "do not interrupt the user while they are working."
        )

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# SPOKEN RESPONSE LENGTH
# ----------------------------------------------------------------------------

def _split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _truncate(text, limit):
    text = text.strip()
    if len(text) <= limit:
        return text

    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit

    trimmed = text[:cut].rstrip(" ,;:-")
    return f"{trimmed}."


def shorten_for_speech(text, length=None, settings=None):
    """Return the short version of a written reply that MAYDAY speaks."""
    s = settings or get_settings()

    clean = " ".join(str(text or "").split())
    if not clean:
        return ""

    chosen = str(length or s["spoken_response_length"]).strip().lower()
    if chosen not in VALID_LENGTHS:
        chosen = s["spoken_response_length"]

    if s["quiet_mode"]:
        chosen = "short"

    if chosen == "detailed":
        return clean

    sentences = _split_sentences(clean)

    if chosen == "medium":
        spoken = " ".join(sentences[:2]) if sentences else clean
        return _truncate(spoken, 260)

    spoken = sentences[0] if sentences else clean
    return _truncate(spoken, 150)


# ----------------------------------------------------------------------------
# ACTION CLASSIFICATION + CONTEXTUAL COMMENTARY
# ----------------------------------------------------------------------------

def classify_action(result, command=""):
    """Work out what kind of action a routed result represents."""
    if not isinstance(result, dict):
        return "unknown"

    status = str(result.get("status", "")).lower()
    text = str(command or "").lower()
    message = str(result.get("message", "")).lower()

    if status == "error":
        return "error"

    if result.get("processes") is not None:
        return "processes"

    if isinstance(result.get("system"), dict) or isinstance(result.get("info"), dict):
        return "system_info"

    if "screenshot" in text or "screenshot" in message:
        return "screenshot"

    if result.get("uri"):
        return "media"

    url = str(result.get("url") or "")
    if url:
        if "search_query" in url or text.startswith(("play ", "put on ")):
            return "media"
        return "site"

    if result.get("application"):
        return "app"

    if result.get("action") in {"shutdown", "restart"}:
        return "power"

    if result.get("action") == "close_window":
        return "window"

    if result.get("results") is not None:
        return "search"

    if result.get("path"):
        return "file"

    return "generic"


def _tone_pools(kind, settings):
    pools = _COMMENTARY.get(kind) or _COMMENTARY["generic"]

    tones = ["neutral"]

    if settings["humour_enabled"] and settings["humour_level"] >= 40:
        tones.append("playful")

    if settings["sarcasm_enabled"] and settings["sarcasm_level"] >= 45:
        tones.append("dry")

    return [pools[tone] for tone in tones if tone in pools]


def _choose(pools, key, avoid=None):
    options = []

    for pool in pools:
        options.extend(pool.get(key, []))

    options = [option for option in options if option]

    if not options:
        return ""

    avoid = avoid or []
    fresh = [option for option in options if option not in avoid]

    return random.choice(fresh or options)


def _ensure_sentence(text):
    text = text.strip()
    if text and text[-1] not in ".!?":
        return f"{text}."
    return text


def comment_on_action(result, command="", base_message=None, settings=None):
    """Add a short, contextual personality comment to a routed action.

    Returns a dict with the on-screen `response`, the short `spoken` version
    and whether commentary was actually added.
    """
    s = settings or get_settings()

    base = _ensure_sentence((base_message or "").strip() or "Command completed.")
    kind = classify_action(result, command)

    # The written response keeps the detail (e.g. the saved path); the spoken
    # version stays short and natural.
    spoken_base = "Screenshot captured." if kind == "screenshot" else base

    plain = {"response": base, "spoken": spoken_base, "kind": kind, "commented": False}

    if not s["personality_enabled"] or s["quiet_mode"]:
        return plain

    if s["commentary_frequency"] == "off":
        return plain

    allowed = _COMMENTARY_KINDS.get(
        s["commentary_frequency"], _COMMENTARY_KINDS["balanced"]
    )

    if kind not in allowed:
        return plain

    now = time.time()

    with _config._lock:
        last_at = _config._last_kind_at.get(kind, 0.0)
        recent = list(_config._recent_comments)

    # Cooldown keeps MAYDAY from commenting on every repeated command.
    if kind != "error" and (now - last_at) < s["commentary_cooldown"]:
        return plain

    pools = _tone_pools(kind, s)

    reaction = _choose(pools, "reactions")
    tail = _choose(pools, "tails", avoid=recent)

    if kind == "error":
        if random.random() > 0.35:
            tail = ""
    else:
        if random.random() > 0.75:
            reaction = ""
        if random.random() > 0.6:
            tail = ""

    response = " ".join(part for part in (reaction, base, tail) if part).strip()

    spoken = " ".join(part for part in (reaction, spoken_base) if part).strip()

    with _config._lock:
        _config._last_comment_at = now
        _config._last_kind_at[kind] = now
        _config._last_comment = tail or reaction or base
        _config._recent_comments.append(tail or reaction)
        del _config._recent_comments[:-6]

    return {
        "response": response,
        "spoken": spoken,
        "kind": kind,
        "commented": True,
    }


# ----------------------------------------------------------------------------
# PUBLIC API
# ----------------------------------------------------------------------------

def get_settings():
    return _config.get()


def update_settings(patch):
    return _config.update(patch)


def reset_settings():
    return _config.reset()


def get_status():
    return {
        "settings": _config.get(),
        "defaults": dict(DEFAULT_SETTINGS),
        "recent_comment": _config._last_comment,
        "timestamp": datetime.now().isoformat(),
    }
