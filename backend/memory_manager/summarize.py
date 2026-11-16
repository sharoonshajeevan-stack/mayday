# ============================================================================
# MAYDAY OS - CONVERSATION SUMMARISATION
# File: backend/memory_manager/summarize.py
# Purpose: Condense a long conversation into a small, durable memory.
#
# Runs entirely offline with simple, explainable rules: it keeps user
# instructions, decisions and unfinished tasks, and throws the rest away. The
# same function signature can later be backed by an LLM summary without any
# caller changing.
# ============================================================================

import re
from collections import Counter

from .models import utcnow

_MAX_SENTENCES = 4

_UNFINISHED = re.compile(
    r"(?i)\b(need to|still need|todo|to-do|next step|haven't|not yet|pending|"
    r"remaining|follow up|follow-up|later|tomorrow|working on)\b"
)
_DECISION = re.compile(
    r"(?i)\b(decided|decision|let's|we'll|we will|going with|chose|chosen|"
    r"settled on|i'll use|we use|switch to|instead)\b"
)
_INSTRUCTION = re.compile(
    r"(?i)\b(always|never|make sure|remember to|from now on|don't|do not)\b"
)

_STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "have", "has",
    "was", "were", "are", "but", "not", "can", "could", "would", "should",
    "what", "when", "where", "which", "how", "why", "who", "about", "into",
    "from", "they", "them", "then", "than", "there", "here", "just", "like",
    "want", "need", "make", "made", "get", "got", "use", "using", "please",
    "will", "been", "being", "does", "did", "doing", "its", "it's", "i'm",
    "let", "sure", "okay", "yeah", "well", "now", "one", "two", "also",
    "mayday", "thanks", "thank",
}


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _match_sentences(exchanges, pattern, limit=_MAX_SENTENCES):
    found = []
    for user, _assistant in exchanges:
        for sentence in _sentences(user):
            if pattern.search(sentence) and sentence not in found:
                found.append(sentence)
        if len(found) >= limit:
            break
    return found[:limit]


def _topics(exchanges, limit=5):
    counter = Counter()
    for user, _assistant in exchanges:
        for token in re.findall(r"[a-z0-9]+", str(user or "").lower()):
            if len(token) >= 4 and token not in _STOPWORDS:
                counter[token] += 1
    return [word for word, _count in counter.most_common(limit)]


def summarize(exchanges):
    """Summarise a list of ``(user, assistant)`` exchanges.

    Returns ``None`` when there is nothing worth keeping.
    """
    exchanges = [
        (str(user or "").strip(), str(assistant or "").strip())
        for user, assistant in (exchanges or [])
        if str(user or "").strip()
    ]

    if not exchanges:
        return None

    topics = _topics(exchanges)
    unfinished = _match_sentences(exchanges, _UNFINISHED)
    decisions = _match_sentences(exchanges, _DECISION)
    instructions = _match_sentences(exchanges, _INSTRUCTION)

    parts = [
        f"Conversation summary ({utcnow()[:10]}), {len(exchanges)} exchanges."
    ]

    if topics:
        parts.append("Topics: " + ", ".join(topics) + ".")
    if unfinished:
        parts.append("Unfinished: " + "; ".join(unfinished) + ".")
    if decisions:
        parts.append("Decisions: " + "; ".join(decisions) + ".")
    if instructions:
        parts.append("User instructions: " + "; ".join(instructions) + ".")

    content = " ".join(parts)

    return {
        "content": content,
        "summary": ("Discussed: " + ", ".join(topics)) if topics else content[:160],
        "topics": topics,
        "unfinished": unfinished,
        "decisions": decisions,
        "instructions": instructions,
    }
