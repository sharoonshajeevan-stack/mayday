# ============================================================================
# MAYDAY OS - MEMORY EXTRACTION
# File: backend/memory_manager/extract.py
# Purpose: Decide which parts of a conversation are worth remembering.
#
# This is a deliberate, offline, rule-based extractor. It is intentionally
# conservative: it prefers to miss a detail than to fill the database with
# chatter. The manager can later add an LLM extractor behind the same
# ``extract_candidates`` interface without changing any caller.
# ============================================================================

import re
from dataclasses import dataclass, field

from .models import Memory, DEFAULT_CATEGORY
from .privacy import contains_secret

MAX_UTTERANCE_CHARS = 400
MIN_CONTENT_CHARS = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QUESTION_STARTERS = (
    "what", "who", "when", "where", "why", "how", "which",
    "do ", "does ", "did ", "is ", "are ", "was ", "were ",
    "can ", "could ", "will ", "would ", "should ", "shall ",
    "am i",
)

# Commands that belong to the system, not to long-term memory.
_IGNORE_STARTERS = (
    "open ", "launch ", "start ", "run ", "close ", "minimize ", "maximize ",
    "restore ", "play ", "pause ", "search ", "google ", "look up ",
    "take a screenshot", "take screenshot", "screenshot", "show processes",
    "list processes", "shut down", "restart", "lock ", "sleep",
    "hello", "hi ", "hey ", "good morning", "good evening", "thanks", "thank you",
    "stop ", "mute", "unmute",
)

_FILLER_TAIL = re.compile(
    r"(?i)\s+(?:please|thanks|thank you|now|asap|okay|ok|buddy|mate)\s*$"
)


def _slug(text, words=4):
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return "-".join(tokens[:words]) or "misc"


def _clean(text):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = value.strip(" \t\"'`")
    value = _FILLER_TAIL.sub("", value).strip()
    value = value.strip(" .,;:!?-")
    return value


def _sentence(text):
    """Return the first sentence of a long utterance, trimmed."""
    value = str(text or "").strip()
    match = re.match(r"^(.*?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def should_ignore(text):
    """True when an utterance should never be turned into a memory."""
    value = str(text or "").strip()
    if not value:
        return True
    if len(value) > MAX_UTTERANCE_CHARS:
        return True

    low = value.lower().strip()

    if low.endswith("?"):
        return True
    if low.startswith(_QUESTION_STARTERS):
        return True
    if low.startswith(_IGNORE_STARTERS):
        return True
    # Single tokens carry no durable information.
    if len(low.split()) < 2:
        return True

    return False


def _preference_slot(value):
    """Map a free-form preference to a stable slot so it can be updated.

    Two phrasings of the same preference (\"short responses\" / \"short
    spoken replies\") must resolve to one memory, not two.
    """
    low = str(value or "").lower()

    if re.search(r"\b(short|brief|concise)\b", low) and re.search(
        r"respons|repl|answer|spoken|talk", low
    ):
        return "response_length"
    if re.search(r"\b(detailed|long|verbose)\b", low) and re.search(
        r"respons|repl|answer|spoken|talk", low
    ):
        return "response_length"
    if re.search(r"\bvoice\b", low):
        return "voice"
    if re.search(r"\bsarcas", low):
        return "sarcasm"
    if re.search(r"\bhumou?r\b", low):
        return "humour"
    if re.search(r"\bcommentar", low):
        return "commentary"
    return None


def _guess_category(content):
    low = str(content or "").lower()

    if re.search(r"\b(project|repo|repository|codebase|feature|branch|build)\b", low):
        return "project"
    if re.search(r"\b(remind|todo|to-do|task|need to|finish|deadline)\b", low):
        return "task"
    if re.search(
        r"\b(pc|computer|laptop|machine|gpu|cpu|ram|vs code|vscode|editor|ide|"
        r"terminal|python|node|docker|error|bug|fix|crash)\b",
        low,
    ):
        return "technical"
    if re.search(
        r"\b(prefer|favourite|favorite|voice|call me|my name|style|tone|like)\b",
        low,
    ):
        return "preference"
    return DEFAULT_CATEGORY


# ---------------------------------------------------------------------------
# Explicit memories ("remember that ...", "save this")
# ---------------------------------------------------------------------------

_REFERENTS = {
    "this", "that", "it", "these", "those",
    "this information", "that information", "this one", "that one",
    "this conversation", "our conversation", "this chat",
}

_EXPLICIT = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+|i want you to\s+)?"
    r"(?:remember|memorize|memorise|save|store|note|make a note)\b"
    r"\s*(?:that|this|the following|these)?\s*[:,\-]?\s*(?P<content>.*)$",
    re.I,
)


def _explicit_memory(text, previous):
    match = _EXPLICIT.match(text)
    if not match:
        return None

    content = _clean(match.group("content"))
    low = content.lower()

    if low in _REFERENTS or not content:
        if not previous:
            return None
        user, assistant = previous
        content = _clean(f"{user} {assistant}")
        if len(content) < MIN_CONTENT_CHARS:
            return None

    if len(content) < MIN_CONTENT_CHARS:
        return None

    category = _guess_category(content)
    return Memory(
        category=category,
        key=f"{category}:explicit:{_slug(content, 6)}",
        content=content,
        summary=content[:160],
        confidence=0.95,
        importance=8,
        source="explicit",
        tags=["explicit"],
    )


# ---------------------------------------------------------------------------
# Pattern rules
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    name: str
    pattern: re.Pattern
    category: str
    content: str
    key: str | None = None
    subject: str | None = None
    confidence: float = 0.75
    importance: int = 6
    tags: tuple = field(default_factory=tuple)


def _rule(name, pattern, category, content, **kwargs):
    return Rule(name, re.compile(pattern, re.I), category, content, **kwargs)


RULES = [
    # --- personal preferences -------------------------------------------
    _rule(
        "name",
        r"\b(?:my name is|i am called|i'm called|call me|i go by)\s+"
        r"(?P<v>[A-Za-z][\w'\-]{1,30}(?:\s+[A-Za-z][\w'\-]{1,30})?)",
        "preference",
        "User's preferred name is {v}.",
        key="preference:name",
        confidence=0.9,
        importance=9,
        tags=("name",),
    ),
    _rule(
        "voice",
        r"\b(?:use|set|switch to|change|prefer)\s+(?:the\s+|my\s+)?voice\s+"
        r"(?:to\s+)?(?P<v>[A-Za-z][\w\-]{2,40})",
        "preference",
        "User prefers the voice '{v}'.",
        key="preference:voice",
        confidence=0.85,
        importance=8,
        tags=("voice",),
    ),
    _rule(
        "response-length",
        r"\b(?:i\s+(?:prefer|like|want)|keep|make|please\s+keep|please\s+use)"
        r"[^.!?]*?\b(?P<v>short|brief|concise|detailed|long|medium)\b[^.!?]*?"
        r"\b(?:responses?|replies|answers|spoken)\b",
        "preference",
        "User prefers {v} responses.",
        key="preference:response_length",
        confidence=0.85,
        importance=8,
        tags=("style",),
    ),
    _rule(
        "prefer",
        r"\b(?:i\s+(?:prefer|like|love|want)|i'd\s+(?:prefer|like)|"
        r"please\s+use)\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "preference",
        "User prefers {v}.",
        confidence=0.8,
        importance=7,
        tags=("preference",),
    ),
    _rule(
        "dislike",
        r"\bi\s+(?:don't|do not|hate|dislike)\s+(?:like\s+)?(?P<v>.+?)(?:\s*[.!?]|$)",
        "preference",
        "User dislikes {v}.",
        confidence=0.8,
        importance=6,
        tags=("preference",),
    ),
    _rule(
        "favourite",
        r"\bmy\s+(?:favourite|favorite)\s+(?P<what>[\w ]{2,25}?)\s+(?:is|are)\s+"
        r"(?P<v>.+?)(?:\s*[.!?]|$)",
        "preference",
        "Favourite {what}: {v}.",
        key="preference:favourite:{what_slug}",
        confidence=0.8,
        importance=6,
        tags=("favourite",),
    ),
    # --- user information ------------------------------------------------
    _rule(
        "learning",
        r"\bi(?:'m| am)\s+(?:currently\s+)?(?:learning|studying)\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "user",
        "User is learning {v}.",
        confidence=0.8,
        importance=7,
        tags=("learning",),
    ),
    _rule(
        "skill",
        r"\bi\s+(?:know|can use|am good at)\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "user",
        "User is skilled with {v}.",
        confidence=0.7,
        importance=6,
        tags=("skill",),
    ),
    # --- project memory --------------------------------------------------
    _rule(
        "project-named",
        r"\b(?:my|the)\s+(?:current\s+|main\s+)?project\s+(?:is\s+)?"
        r"(?:called|named)\s+"
        r"(?P<v>[A-Za-z0-9][\w\-]*(?:\s+[A-Za-z0-9][\w\-]*){0,2})"
        r"(?=\s*(?:and\b|,|\.|!|\?|$|which\b|that\b))",
        "project",
        "Active project '{v}'.",
        key="project:{v_slug}:identity",
        subject="{v}",
        confidence=0.9,
        importance=9,
        tags=("project",),
    ),
    _rule(
        "project-is",
        r"\bmy\s+(?:current\s+|main\s+)?project\s+is\s+"
        r"(?!(?:called|named|about|at|in|on)\b)"
        r"(?P<v>[A-Za-z0-9][\w\-]*(?:\s+[A-Za-z0-9][\w\-]*){0,2})"
        r"(?=\s*(?:and\b|,|\.|!|\?|$|which\b|that\b))",
        "project",
        "Active project '{v}'.",
        key="project:{v_slug}:identity",
        subject="{v}",
        confidence=0.8,
        importance=9,
        tags=("project",),
    ),
    _rule(
        "working-on",
        r"\bi(?:'m| am)\s+(?:currently\s+)?working on\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "project",
        "Currently working on: {v}",
        key="project:progress:{v_slug}",
        confidence=0.85,
        importance=8,
        tags=("progress",),
    ),
    _rule(
        "project-uses",
        r"\b(?:it|the project|my project|this project)\s+uses\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "project",
        "Project uses {v}.",
        key="project:tech:{v_slug}",
        confidence=0.85,
        importance=7,
        tags=("tech",),
    ),
    _rule(
        "project-built-with",
        r"\b(?:built|written|coded)\s+(?:with|in)\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "project",
        "Project built with {v}.",
        key="project:tech:{v_slug}",
        confidence=0.8,
        importance=7,
        tags=("tech",),
    ),
    _rule(
        "project-location",
        r"\b(?:my|the)\s+project\s+(?:is\s+)?(?:located\s+|stored\s+)?"
        r"(?:at|in)\s+(?P<v>[A-Za-z]:\\[^,.;]+|/[\w/.\-]+)",
        "project",
        "Project location: {v}",
        key="project:location",
        confidence=0.85,
        importance=8,
        tags=("location",),
    ),
    # --- task memory -----------------------------------------------------
    _rule(
        "remind",
        r"\bremind me to\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "task",
        "Pending task: {v}",
        key="task:pending:{v_slug}",
        confidence=0.9,
        importance=7,
        tags=("pending",),
    ),
    _rule(
        "todo",
        r"^(?:add\s+)?(?:a\s+)?to-?do\s*[:\-]?\s*(?P<v>.+?)(?:\s*[.!?]|$)",
        "task",
        "Pending task: {v}",
        key="task:pending:{v_slug}",
        confidence=0.9,
        importance=7,
        tags=("pending",),
    ),
    _rule(
        "need-to",
        r"\bi\s+(?:still\s+)?need to\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "task",
        "Pending task: {v}",
        key="task:pending:{v_slug}",
        confidence=0.8,
        importance=7,
        tags=("pending",),
    ),
    _rule(
        "completed",
        r"\bi\s+(?:just\s+)?(?:finished|completed|am done with|done with)\s+"
        r"(?P<v>.+?)(?:\s*[.!?]|$)",
        "task",
        "Completed task: {v}",
        key="task:completed:{v_slug}",
        confidence=0.85,
        importance=6,
        tags=("completed",),
    ),
    _rule(
        "failed",
        r"\b(?P<v>.+?)\s+(?:failed|broke|is broken|keeps failing)\s+"
        r"(?:because|due to|since)\s+(?P<why>.+?)(?:\s*[.!?]|$)",
        "task",
        "{v} failed because {why}.",
        key="task:failed:{v_slug}",
        confidence=0.8,
        importance=7,
        tags=("failed",),
    ),
    # --- technical memory ------------------------------------------------
    _rule(
        "hardware",
        r"\bmy\s+(?:pc|computer|laptop|machine|rig|setup)\s+"
        r"(?:has|is|runs|uses)\s+(?P<v>.+?)(?:\s*[.!?]|$)",
        "technical",
        "Computer: {v}.",
        key="technical:hardware",
        confidence=0.8,
        importance=7,
        tags=("hardware",),
    ),
    _rule(
        "environment",
        r"\bmy\s+(?P<what>editor|ide|terminal|shell|os|browser|distro)\s+is\s+"
        r"(?P<v>.+?)(?:\s*[.!?]|$)",
        "technical",
        "Preferred {what}: {v}.",
        key="technical:env:{what_slug}",
        confidence=0.85,
        importance=7,
        tags=("environment",),
    ),
    _rule(
        "tool-for",
        r"\bi\s+use\s+(?P<tool>[\w][\w\-\. ]{0,30}?)\s+(?:as|for)\s+"
        r"(?:my\s+)?(?P<what>[\w][\w\- ]{0,40}?)(?:\s*[.!?]|$)",
        "technical",
        "Uses {tool} for {what}.",
        key="technical:tool:{what_slug}",
        confidence=0.7,
        importance=6,
        tags=("tools",),
    ),
    _rule(
        "fix",
        r"\b(?:the\s+)?(?:fix|solution|workaround)\s+(?:was|is)\s+"
        r"(?P<v>.+?)(?:\s*[.!?]|$)",
        "technical",
        "Troubleshooting fix: {v}",
        confidence=0.85,
        importance=8,
        tags=("troubleshooting",),
    ),
    _rule(
        "fixed-by",
        r"\bi\s+fixed\s+(?P<what>.+?)\s+by\s+(?P<how>.+?)(?:\s*[.!?]|$)",
        "technical",
        "Fixed {what} by {how}.",
        confidence=0.85,
        importance=8,
        tags=("troubleshooting",),
    ),
]


def _values(match):
    values = {}
    for name, value in match.groupdict().items():
        value = _clean(value)
        values[name] = value
        values[f"{name}_slug"] = _slug(value)
    return values


def _build(rule, values):
    try:
        content = rule.content.format(**values)
    except (KeyError, IndexError):
        return None

    content = _clean(content)
    if len(content) < MIN_CONTENT_CHARS:
        return None

    key = rule.key
    if key:
        try:
            key = key.format(**values)
        except (KeyError, IndexError):
            key = None
    elif rule.name in {"prefer", "dislike"}:
        # Free-form preferences still get a slot when we can recognise one,
        # so "I prefer short responses" and "I prefer short spoken replies"
        # update the same record instead of piling up.
        slot = _preference_slot(values.get("v"))
        key = f"preference:{slot}" if slot else None

    subject = rule.subject
    if subject:
        try:
            subject = _clean(subject.format(**values))
        except (KeyError, IndexError):
            subject = None

    return Memory(
        category=rule.category,
        key=key,
        subject=subject,
        content=content,
        summary=content[:160],
        confidence=rule.confidence,
        importance=rule.importance,
        source="auto",
        tags=list(rule.tags),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_candidates(text, previous=None):
    """Return the long-term memories worth saving from one utterance.

    ``previous`` is an optional ``(user, assistant)`` pair used to resolve
    "remember this".
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    # Explicit requests are handled first and always win.
    explicit = _explicit_memory(raw, previous)
    if explicit is not None:
        return [explicit]

    if should_ignore(raw):
        return []

    sentence = _sentence(raw)
    candidates = []
    seen = set()

    for rule in RULES:
        match = rule.pattern.search(sentence)
        if not match:
            continue

        memory = _build(rule, _values(match))
        if memory is None:
            continue

        # Never store credentials.
        if contains_secret(memory.content):
            continue

        fingerprint = memory.key or memory.content.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        candidates.append(memory)

    # If the utterance named a project, attribute its project memories to it.
    subject = next(
        (m.subject for m in candidates if m.category == "project" and m.subject),
        None,
    )
    if subject:
        for memory in candidates:
            if memory.category == "project" and not memory.subject:
                memory.subject = subject

    return candidates
