# ============================================================================
# MAYDAY OS - MEMORY MANAGER (long-term memory)
# File: backend/memory_manager/models.py
# Purpose: Domain model for structured, persistent long-term memory.
#
# The six categories below are the ones the product spec asks MAYDAY to
# remember. Every stored record carries a category, a confidence score and
# created/updated timestamps so retrieval can prefer recent, trusted facts.
# ============================================================================

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

CATEGORIES = {
    "preference": "Personal preferences",
    "user": "User information",
    "project": "Project memory",
    "conversation": "Conversation memory",
    "task": "Task memory",
    "technical": "Technical memory",
}

DEFAULT_CATEGORY = "user"

SOURCES = {"explicit", "auto", "summary", "user_edit", "system"}

# Categories that describe the user globally (as opposed to one project).
GLOBAL_CATEGORIES = {"preference", "user", "technical"}


def utcnow():
    """Timezone-aware ISO-8601 timestamp, second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_category(value):
    value = str(value or "").strip().lower()
    return value if value in CATEGORIES else DEFAULT_CATEGORY


def clamp_confidence(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.7
    return max(0.0, min(1.0, value))


def clamp_importance(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(10, value))


@dataclass
class Memory:
    """A single long-term memory record."""

    id: int | None = None
    category: str = DEFAULT_CATEGORY
    key: str | None = None
    subject: str | None = None
    content: str = ""
    summary: str = ""
    confidence: float = 0.7
    importance: int = 5
    source: str = "auto"
    tags: list = field(default_factory=list)
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    access_count: int = 0
    last_accessed_at: str | None = None
    verified: int = 1
    pinned: int = 0

    def __post_init__(self):
        self.category = normalize_category(self.category)
        self.confidence = clamp_confidence(self.confidence)
        self.importance = clamp_importance(self.importance)
        self.source = self.source if self.source in SOURCES else "auto"
        if not isinstance(self.tags, list):
            self.tags = []
        self.tags = [str(tag) for tag in self.tags if str(tag or "").strip()]
        self.content = str(self.content or "").strip()
        self.summary = str(self.summary or "").strip()
        self.key = str(self.key).strip() if self.key else None
        self.subject = str(self.subject).strip() if self.subject else None
        self.verified = 1 if self.verified else 0
        self.pinned = 1 if self.pinned else 0

    def to_dict(self):
        data = asdict(self)
        data["tags"] = list(self.tags)
        data["category_label"] = CATEGORIES.get(self.category, self.category)
        return data

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None

        try:
            tags = json.loads(row["tags"] or "[]")
        except (TypeError, ValueError):
            tags = []

        return cls(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            subject=row["subject"],
            content=row["content"],
            summary=row["summary"],
            confidence=row["confidence"],
            importance=row["importance"],
            source=row["source"],
            tags=tags,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=row["access_count"],
            last_accessed_at=row["last_accessed_at"],
            verified=row["verified"],
            pinned=row["pinned"],
        )
