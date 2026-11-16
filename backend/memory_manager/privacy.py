# ============================================================================
# MAYDAY OS - MEMORY PRIVACY GUARD
# File: backend/memory_manager/privacy.py
# Purpose: Make sure credentials never reach the memory database.
#
# Every string that could be persisted is passed through :func:`contains_secret`
# first. The patterns are deliberately conservative: a false positive only means
# MAYDAY stays quiet about a value - never that a secret is written to disk.
# ============================================================================

import re

PLACEHOLDER = "[redacted]"

# Credential shapes we recognise. Ordered roughly by specificity.
_SECRET_PATTERNS = [
    # Provider API keys.
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),                      # OpenAI
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),                     # Google
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{10,}\b"),                     # Gemini
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),                        # GitHub PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),               # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                            # AWS key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{10,}\b"),                    # Stripe
    re.compile(r"\bAIzaSy[A-Za-z0-9_\-]{20,}\b"),
    # JSON Web Tokens / bearer tokens.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b"),
    re.compile(r"\bbearer\s+[A-Za-z0-9._\-]{16,}\b", re.I),
    # "password: hunter2" / "api_key = abc" style assignments.
    re.compile(
        r"(?i)\b(?:api[_\- ]?key|secret|token|password|passwd|pwd|credential)s?\b"
        r"\s*(?:is|are|[:=])\s*\S+"
    ),
    # "my password is hunter2"
    re.compile(r"(?i)\bmy\s+(?:password|passphrase|pin)\s+is\s+\S+"),
    # Private key blocks.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def contains_secret(text):
    """True when ``text`` looks like it carries a credential."""
    value = str(text or "")
    if not value:
        return False
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def redact(text):
    """Return ``text`` with any credential-looking spans replaced."""
    value = str(text or "")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(PLACEHOLDER, value)
    return value


def sanitize(text):
    """Return ``(clean_text, was_redacted)``.

    ``clean_text`` is safe to store; ``was_redacted`` is True when something
    was removed so callers can tell the user MAYDAY kept quiet on purpose.
    """
    value = str(text or "")
    clean = redact(value)
    return clean, clean != value
