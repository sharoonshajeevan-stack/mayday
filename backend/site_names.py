# ============================================================================
# MAYDAY OS - FRIENDLY SITE NAMES
# File: backend/site_names.py
# Purpose: Turn a URL into a short, speakable name so MAYDAY says
#          "Opening youtube" instead of "Opening https://www.youtube.com".
# ============================================================================

from urllib.parse import urlparse

# Known sites get a clean, human-friendly name.
KNOWN_SITE_NAMES = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "google.com": "google",
    "github.com": "github",
    "gmail.com": "gmail",
    "mail.google.com": "gmail",
    "twitter.com": "twitter",
    "x.com": "x",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "reddit.com": "reddit",
    "wikipedia.org": "wikipedia",
    "amazon.com": "amazon",
    "netflix.com": "netflix",
    "spotify.com": "spotify",
    "linkedin.com": "linkedin",
    "openai.com": "openai",
    "chatgpt.com": "chatgpt",
    "chat.openai.com": "chatgpt",
    "stackoverflow.com": "stack overflow",
    "whatsapp.com": "whatsapp",
    "web.whatsapp.com": "whatsapp",
    "twitch.tv": "twitch",
    "discord.com": "discord",
    "pinterest.com": "pinterest",
    "tiktok.com": "tiktok",
}

# Sub-domains that should not become the spoken name.
_SUBDOMAINS = {
    "www",
    "m",
    "web",
    "mail",
    "chat",
    "docs",
    "drive",
    "maps",
    "news",
    "play",
    "open",
    "en",
    "app",
}

# Second-level labels used by country-code domains (example.co.uk).
_COUNTRY_SECOND_LEVELS = {"co", "com", "org", "net", "gov", "ac", "edu"}


def friendly_site_name(url):
    """Return a short, speakable name for a URL (e.g. 'youtube')."""
    text = str(url or "").strip()

    if not text:
        return text

    if not text.startswith(("http://", "https://")):
        text = "https://" + text

    try:
        host = urlparse(text).netloc.lower()
    except ValueError:
        host = text.lower()

    # Drop any user-info and port.
    host = host.split("@")[-1].split(":")[0]

    if host in KNOWN_SITE_NAMES:
        return KNOWN_SITE_NAMES[host]

    labels = [label for label in host.split(".") if label]

    if len(labels) > 2 and labels[0] in _SUBDOMAINS:
        labels = labels[1:]

    stripped = ".".join(labels)

    if stripped in KNOWN_SITE_NAMES:
        return KNOWN_SITE_NAMES[stripped]

    # example.co.uk -> example (skip a country-code second-level label).
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and labels[-2] in _COUNTRY_SECOND_LEVELS
    ):
        return labels[-3]

    if len(labels) >= 2:
        return labels[-2]

    return labels[0] if labels else text
