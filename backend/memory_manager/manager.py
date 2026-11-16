# ============================================================================
# MAYDAY OS - MEMORY MANAGER
# File: backend/memory_manager/manager.py
# Purpose: The single long-term memory API used by the brain, the Flask
#          endpoints and the real-time Pipecat pipeline.
#
# The manager owns the SQLite store, the extraction/retrieval policy, the
# privacy guard and the in-session conversation buffer used for summaries.
# It never touches the microphone or camera: only text is ever persisted.
# ============================================================================

import logging
import os
import threading
from pathlib import Path

from . import retrieve as retrieve_module
from . import summarize as summarize_module
from .extract import extract_candidates
from .models import CATEGORIES, DEFAULT_CATEGORY, Memory, utcnow
from .privacy import contains_secret, sanitize
from .store import MemoryStore, content_hash

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / "memory" / "mayday_memory.db"

MIN_CONTENT_CHARS = 3


def _env_bool(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _clean(text):
    value = " ".join(str(text or "").split())
    return value.strip(" \t\"'`").strip()


class MemoryManager:
    """Facade over the SQLite memory store."""

    def __init__(self, db_path=None):
        resolved = (
            os.getenv("MAYDAY_MEMORY_DB")
            or db_path
            or str(DEFAULT_DB)
        )
        path = Path(resolved)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = str(path)
        self.store = MemoryStore(self.db_path)

        self._lock = threading.RLock()
        self._last_exchange = None
        self._session_buffer = []
        self._session_memory_ids = []
        self._ignore_session = False

        # Environment defaults; the user can override them from the UI, and
        # the override is stored in the database so it survives a restart.
        self._env_defaults = {
            "auto_capture": _env_bool("MAYDAY_MEMORY_AUTOCAPTURE", True),
            "retrieval_enabled": _env_bool("MAYDAY_MEMORY_RETRIEVAL", True),
            "summarize_enabled": _env_bool("MAYDAY_MEMORY_SUMMARIZE", True),
        }
        self._summary_after = int(os.getenv("MAYDAY_MEMORY_SUMMARY_AFTER", "12"))

        logger.info("Long-term memory ready (%s)", self.db_path)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _setting(self, name):
        stored = self.store.get_setting(f"setting:{name}")
        if stored is None:
            return self._env_defaults.get(name, True)
        return str(stored).strip().lower() in {"1", "true", "yes", "on"}

    def _write_setting(self, name, value):
        self.store.set_setting(f"setting:{name}", "true" if value else "false")

    @property
    def auto_capture(self):
        return self._setting("auto_capture")

    @property
    def retrieval_enabled(self):
        return self._setting("retrieval_enabled")

    @property
    def summarize_enabled(self):
        return self._setting("summarize_enabled")

    def get_settings(self):
        return {
            "auto_capture": self.auto_capture,
            "retrieval_enabled": self.retrieval_enabled,
            "summarize_enabled": self.summarize_enabled,
            "summary_after": self._summary_after,
            "db_path": self.db_path,
            "categories": CATEGORIES,
        }

    def update_settings(self, patch):
        patch = patch or {}

        if "auto_capture" in patch:
            self._write_setting("auto_capture", bool(patch["auto_capture"]))
        if "retrieval_enabled" in patch:
            self._write_setting("retrieval_enabled", bool(patch["retrieval_enabled"]))
        if "summarize_enabled" in patch:
            self._write_setting("summarize_enabled", bool(patch["summarize_enabled"]))

        return self.get_settings()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def remember(
        self,
        content,
        category=None,
        key=None,
        subject=None,
        confidence=0.7,
        importance=6,
        source="explicit",
        tags=None,
        summary=None,
    ):
        """Store one memory, de-duplicating and resolving contradictions."""
        text = _clean(content)

        if len(text) < MIN_CONTENT_CHARS:
            return {"status": "skipped", "reason": "empty"}

        if contains_secret(text):
            logger.warning("Memory blocked: looked like a credential")
            return {"status": "blocked", "reason": "secret"}

        clean, redacted = sanitize(text)
        if redacted:
            # Partial redaction: keep the useful remainder only if it still
            # says something. Otherwise drop it entirely.
            if len(clean) < MIN_CONTENT_CHARS or clean == "[redacted]":
                return {"status": "blocked", "reason": "secret"}
            text = clean

        memory = Memory(
            category=category or DEFAULT_CATEGORY,
            key=key,
            subject=subject,
            content=text,
            summary=summary or text[:160],
            confidence=confidence,
            importance=importance,
            source=source,
            tags=list(tags or []),
        )

        digest = content_hash(text)

        with self._lock:
            duplicate = self.store.find_by_hash(digest)
            if duplicate is not None:
                # Same fact again: refresh confidence/recency, don't duplicate.
                self.store.update(
                    duplicate.id,
                    confidence=max(duplicate.confidence, memory.confidence),
                )
                self._track(duplicate.id)
                return {
                    "status": "duplicate",
                    "memory": self.store.get(duplicate.id).to_dict(),
                }

            if memory.key:
                existing = self.store.find_by_key(memory.key)
                if existing:
                    newest = existing[0]
                    previous = newest.content
                    if previous.strip().lower() != text.strip().lower():
                        # Contradiction: update in place, keep the history in
                        # the event by returning `previous`.
                        self.store.update(
                            newest.id,
                            content=text,
                            summary=memory.summary,
                            category=memory.category,
                            subject=memory.subject,
                            confidence=max(memory.confidence, newest.confidence),
                            importance=max(memory.importance, newest.importance),
                            tags=memory.tags,
                            source=source,
                        )
                        # Remove older duplicates of the same slot.
                        for stale in existing[1:]:
                            self.store.delete(stale.id)
                        self._track(newest.id)
                        return {
                            "status": "updated",
                            "previous": previous,
                            "memory": self.store.get(newest.id).to_dict(),
                        }

                    self.store.update(
                        newest.id,
                        confidence=max(newest.confidence, memory.confidence),
                    )
                    self._track(newest.id)
                    return {
                        "status": "duplicate",
                        "memory": self.store.get(newest.id).to_dict(),
                    }

            stored = self.store.insert(memory)
            self._track(stored.id)
            return {"status": "saved", "memory": stored.to_dict()}

    def _track(self, memory_id):
        if memory_id is not None and memory_id not in self._session_memory_ids:
            self._session_memory_ids.append(memory_id)

    def update_memory(self, memory_id, **fields):
        memory = self.store.update(memory_id, **fields)
        return memory.to_dict() if memory else None

    def delete_memory(self, memory_id):
        return self.store.delete(memory_id)

    def delete_matching(self, query, limit=5):
        """Delete memories matching ``query``. Returns the deleted records."""
        matches = retrieve_module.retrieve(
            query, self.store, limit=limit, min_score=0.2
        )
        deleted = []
        for memory in matches:
            if self.store.delete(memory.id):
                deleted.append(memory.to_dict())
        return deleted

    def clear(self, categories=None):
        return self.store.clear(categories)

    # ------------------------------------------------------------------
    # Automatic capture
    # ------------------------------------------------------------------
    def observe(self, user_text, assistant_text=""):
        """Extract and store anything worth remembering from an exchange."""
        if not self.auto_capture or self._ignore_session:
            return []

        candidates = extract_candidates(user_text, previous=self._last_exchange)

        saved = []
        for candidate in candidates:
            result = self.remember(
                candidate.content,
                category=candidate.category,
                key=candidate.key,
                subject=candidate.subject,
                confidence=candidate.confidence,
                importance=candidate.importance,
                source=candidate.source,
                tags=candidate.tags,
                summary=candidate.summary,
            )
            if result.get("status") in {"saved", "updated"}:
                saved.append(result)

        with self._lock:
            self._last_exchange = (str(user_text or ""), str(assistant_text or ""))
            self._session_buffer.append(
                (str(user_text or ""), str(assistant_text or ""))
            )
            should_summarize = (
                self.summarize_enabled
                and len(self._session_buffer) >= self._summary_after
            )

        if should_summarize:
            self.summarize_session()

        return saved

    def summarize_session(self):
        """Condense the buffered conversation into one durable memory."""
        with self._lock:
            buffer = list(self._session_buffer)

        summary = summarize_module.summarize(buffer)
        if not summary:
            with self._lock:
                self._session_buffer = buffer[-2:]
            return None

        self.remember(
            summary["content"],
            category="conversation",
            key=f"conversation:{utcnow()[:10]}",
            confidence=0.7,
            importance=6,
            source="summary",
            tags=["summary"],
            summary=summary["summary"],
        )

        for task in summary["unfinished"]:
            self.remember(
                task,
                category="task",
                key=f"task:pending:{content_hash(task)[:10]}",
                confidence=0.6,
                importance=6,
                source="summary",
                tags=["pending", "unfinished"],
            )

        with self._lock:
            # Keep a little tail so the next summary has continuity.
            self._session_buffer = buffer[-2:]

        return summary

    def end_conversation(self):
        """Summarise whatever is left when a session ends."""
        with self._lock:
            has_buffer = bool(self._session_buffer)

        if has_buffer and self.summarize_enabled:
            return self.summarize_session()

        with self._lock:
            self._session_buffer = []
            self._last_exchange = None
        return None

    def ignore_conversation(self):
        """Stop remembering this conversation and drop what it captured."""
        with self._lock:
            self._ignore_session = True
            ids = list(self._session_memory_ids)
            self._session_memory_ids = []
            self._session_buffer = []
            self._last_exchange = None

        removed = 0
        for memory_id in ids:
            if self.store.delete(memory_id):
                removed += 1

        return removed

    def resume_capture(self):
        with self._lock:
            self._ignore_session = False

    def note_exchange(self, user_text, assistant_text=""):
        """Record an exchange for context/summaries without extracting facts.

        Used when a turn was handled by an explicit memory command, so the
        conversation still flows but nothing is auto-extracted twice.
        """
        with self._lock:
            self._last_exchange = (str(user_text or ""), str(assistant_text or ""))
            self._session_buffer.append(
                (str(user_text or ""), str(assistant_text or ""))
            )
            should_summarize = (
                self.summarize_enabled
                and len(self._session_buffer) >= self._summary_after
            )

        if should_summarize:
            self.summarize_session()

    def remember_last_exchange(self):
        """Save the most recent exchange when the user says "remember this"."""
        with self._lock:
            previous = self._last_exchange

        if not previous:
            return None

        user, assistant = previous
        content = _clean(f"{user} {assistant}")

        if len(content) < MIN_CONTENT_CHARS:
            return None

        return self.remember(
            content,
            category="user",
            key=None,
            confidence=0.9,
            importance=7,
            source="explicit",
            tags=["explicit"],
            summary=_clean(user)[:160] or content[:160],
        )

    def forget_latest(self):
        """Delete the most recently updated memory. Returns it, or None."""
        memories = self.store.list(limit=1, order="updated")
        if not memories:
            return None

        target = memories[0]
        if self.store.delete(target.id):
            return target.to_dict()
        return None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def retrieve(self, query, limit=6, categories=None):
        if not self.retrieval_enabled:
            return []
        return retrieve_module.retrieve(
            query, self.store, limit=limit, categories=categories
        )

    def retrieve_context(self, query, limit=6):
        memories = self.retrieve(query, limit=limit)
        for memory in memories:
            self.store.touch(memory.id)
        return retrieve_module.format_context(memories)

    def recall(self, query, limit=6):
        return [memory.to_dict() for memory in self.retrieve(query, limit=limit)]

    def get(self, memory_id):
        memory = self.store.get(memory_id)
        return memory.to_dict() if memory else None

    def list(self, category=None, limit=200, offset=0, order="updated", query=None):
        if query:
            hits = self.store.search(query, limit=limit, category=category)
            return [memory.to_dict() for memory, _score in hits]
        return [
            memory.to_dict()
            for memory in self.store.list(
                category=category, limit=limit, offset=offset, order=order
            )
        ]

    def search(self, query, limit=20, category=None):
        hits = self.store.search(query, limit=limit, category=category)
        results = []
        for memory, score in hits:
            item = memory.to_dict()
            item["score"] = round(float(score), 4)
            results.append(item)
        return results

    def subjects(self):
        return self.store.distinct_subjects()

    def export(self):
        return {
            "timestamp": utcnow(),
            "total": self.store.count(),
            "categories": CATEGORIES,
            "memories": self.store.export(),
        }

    def stats(self):
        counts = self.store.counts_by_category()
        return {
            "total": self.store.count(),
            "by_category": {name: counts.get(name, 0) for name in CATEGORIES},
            "projects": self.store.distinct_subjects(),
            "db_path": self.db_path,
            "timestamp": utcnow(),
        }

    def status(self):
        settings = self.get_settings()
        return {
            "total": self.store.count(),
            "settings": settings,
            "session_buffer": len(self._session_buffer),
            "capture_paused": self._ignore_session,
            "db_path": self.db_path,
            "timestamp": utcnow(),
        }


# ============================================================================
# Global instance + module-level helpers
# ============================================================================

memory_manager = MemoryManager()
