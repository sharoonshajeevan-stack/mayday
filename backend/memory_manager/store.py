# ============================================================================
# MAYDAY OS - MEMORY STORE (SQLite)
# File: backend/memory_manager/store.py
# Purpose: Durable, offline, local storage for MAYDAY's long-term memory.
#
# Design notes
# ------------
# * SQLite (stdlib) - no server, no network, survives restarts and reboots.
# * A full-text index (FTS5) gives fast keyword search. If the local SQLite
#   build has no FTS5 the store degrades to LIKE queries automatically.
# * The schema is versioned in ``memory_meta`` so a future move to a vector
#   database can migrate rows without changing callers: every memory already
#   carries a stable ``key``, ``subject``, ``category`` and ``content_hash``.
# * An optional ``embedding`` column is reserved for that migration; it is not
#   populated today because semantic search is not required yet.
# ============================================================================

import hashlib
import json
import logging
import re
import sqlite3
import threading
from contextlib import closing

from .models import Memory, utcnow

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Stopwords dropped from search expressions: they carry no retrieval signal.
_STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "have", "has",
    "are", "was", "were", "but", "not", "can", "could", "would", "should",
    "what", "when", "where", "which", "how", "why", "who", "about", "into",
    "from", "they", "them", "then", "than", "there", "here", "just", "like",
    "want", "need", "make", "get", "got", "use", "using", "please", "will",
    "been", "being", "does", "did", "its", "let", "sure", "okay", "now", "also",
    "my", "our", "his", "her", "him", "she", "it", "is", "am", "be", "do", "of",
    "to", "in", "on", "at", "or", "as", "an", "a", "i", "we", "me", "us", "all",
    "one", "two", "more", "most", "much", "very", "really", "still", "tell",
    "give", "show", "know", "think", "some", "any",
}

# Columns a caller may change through :meth:`MemoryStore.update`.
_EDITABLE = {
    "category",
    "key",
    "subject",
    "content",
    "summary",
    "confidence",
    "importance",
    "source",
    "tags",
    "verified",
    "pinned",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    category         TEXT    NOT NULL,
    key              TEXT,
    subject          TEXT,
    content          TEXT    NOT NULL,
    summary          TEXT    NOT NULL DEFAULT '',
    content_hash     TEXT    NOT NULL,
    confidence       REAL    NOT NULL DEFAULT 0.7,
    importance       INTEGER NOT NULL DEFAULT 5,
    source           TEXT    NOT NULL DEFAULT 'auto',
    tags             TEXT    NOT NULL DEFAULT '[]',
    embedding        BLOB,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    access_count     INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    verified         INTEGER NOT NULL DEFAULT 1,
    pinned           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_key      ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_subject  ON memories(subject);
CREATE INDEX IF NOT EXISTS idx_memories_hash     ON memories(content_hash);
CREATE INDEX IF NOT EXISTS idx_memories_updated  ON memories(updated_at);

CREATE TABLE IF NOT EXISTS memory_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, summary, subject, tags,
    content='memories',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, summary, subject, tags)
    VALUES (new.id, new.content, new.summary, new.subject, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, subject, tags)
    VALUES ('delete', old.id, old.content, old.summary, old.subject, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, subject, tags)
    VALUES ('delete', old.id, old.content, old.summary, old.subject, old.tags);
    INSERT INTO memories_fts(rowid, content, summary, subject, tags)
    VALUES (new.id, new.content, new.summary, new.subject, new.tags);
END;
"""


def content_hash(content):
    """Stable hash used to detect duplicate memories."""
    normalized = re.sub(r"\s+", " ", str(content or "").strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _fts_match(query):
    """Turn free text into a safe FTS5 OR-query, or None."""
    tokens = re.findall(r"[A-Za-z0-9_]+", str(query or "").lower())
    tokens = [
        token
        for token in tokens
        if len(token) >= 2 and token not in _STOPWORDS
    ]
    if not tokens:
        return None
    # De-duplicate while keeping order, cap the expression size.
    seen = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return " OR ".join(f'"{token}"' for token in seen[:16])


class MemoryStore:
    """Thin, thread-safe wrapper around the SQLite memory database."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self.has_fts = True
        self.initialize()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self):
        """Create the schema (idempotent) and record the schema version."""
        with self._lock:
            with closing(self._connect()) as connection:
                connection.executescript(_SCHEMA)

                try:
                    connection.executescript(_FTS_SCHEMA)
                    self.has_fts = True
                except sqlite3.OperationalError as exc:  # pragma: no cover
                    logger.warning(
                        "FTS5 unavailable, falling back to LIKE search: %s", exc
                    )
                    self.has_fts = False

                connection.execute(
                    "INSERT OR IGNORE INTO memory_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                connection.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def insert(self, memory):
        memory = memory if isinstance(memory, Memory) else Memory(**memory)
        digest = content_hash(memory.content)
        now = utcnow()
        memory.created_at = memory.created_at or now
        memory.updated_at = now

        with self._lock:
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO memories (
                        category, key, subject, content, summary, content_hash,
                        confidence, importance, source, tags,
                        created_at, updated_at, access_count, last_accessed_at,
                        verified, pinned
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory.category,
                        memory.key,
                        memory.subject,
                        memory.content,
                        memory.summary,
                        digest,
                        memory.confidence,
                        memory.importance,
                        memory.source,
                        json.dumps(memory.tags),
                        memory.created_at,
                        memory.updated_at,
                        memory.access_count,
                        memory.last_accessed_at,
                        memory.verified,
                        memory.pinned,
                    ),
                )
                memory.id = cursor.lastrowid
                connection.commit()

        return memory

    def update(self, memory_id, **fields):
        patch = {k: v for k, v in fields.items() if k in _EDITABLE}
        if not patch:
            return self.get(memory_id)

        if "tags" in patch and not isinstance(patch["tags"], str):
            patch["tags"] = json.dumps(list(patch["tags"] or []))

        if "content" in patch:
            patch["content_hash"] = content_hash(patch["content"])

        patch["updated_at"] = utcnow()

        columns = ", ".join(f"{name} = ?" for name in patch)
        values = list(patch.values()) + [memory_id]

        with self._lock:
            with closing(self._connect()) as connection:
                connection.execute(
                    f"UPDATE memories SET {columns} WHERE id = ?", values
                )
                connection.commit()

        return self.get(memory_id)

    def delete(self, memory_id):
        with self._lock:
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    "DELETE FROM memories WHERE id = ?", (memory_id,)
                )
                connection.commit()
                return cursor.rowcount > 0

    def touch(self, memory_id):
        """Record that a memory was used (feeds the retrieval ranking)."""
        with self._lock:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    UPDATE memories
                       SET access_count = access_count + 1,
                           last_accessed_at = ?
                     WHERE id = ?
                    """,
                    (utcnow(), memory_id),
                )
                connection.commit()

    def clear(self, categories=None):
        """Delete every memory, or only the given categories. Returns count."""
        with self._lock:
            with closing(self._connect()) as connection:
                if categories:
                    placeholders = ", ".join("?" for _ in categories)
                    cursor = connection.execute(
                        f"DELETE FROM memories WHERE category IN ({placeholders})",
                        list(categories),
                    )
                else:
                    cursor = connection.execute("DELETE FROM memories")
                connection.commit()
                return cursor.rowcount

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, memory_id):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return Memory.from_row(row)

    def find_by_key(self, key):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE key = ? ORDER BY updated_at DESC",
                (key,),
            ).fetchall()
        return [Memory.from_row(row) for row in rows]

    def find_by_hash(self, digest):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE content_hash = ? LIMIT 1", (digest,)
            ).fetchone()
        return Memory.from_row(row)

    def list(self, category=None, limit=200, offset=0, order="updated"):
        order_sql = {
            "updated": "updated_at DESC, id DESC",
            "created": "created_at DESC, id DESC",
            "importance": "pinned DESC, importance DESC, updated_at DESC",
        }.get(order, "updated_at DESC, id DESC")

        sql = "SELECT * FROM memories"
        params = []

        if category:
            sql += " WHERE category = ?"
            params.append(category)

        sql += f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [Memory.from_row(row) for row in rows]

    def search(self, query, limit=20, category=None):
        """Keyword search. Returns a list of ``(Memory, score)`` tuples.

        ``score`` is a positive number where larger is a better match.
        """
        match = _fts_match(query)

        if self.has_fts and match:
            try:
                return self._search_fts(match, limit, category)
            except sqlite3.OperationalError as exc:  # pragma: no cover
                logger.warning("FTS query failed, using LIKE fallback: %s", exc)

        return self._search_like(query, limit, category)

    def _search_fts(self, match, limit, category):
        sql = (
            "SELECT m.*, bm25(memories_fts) AS rank "
            "FROM memories_fts "
            "JOIN memories m ON m.id = memories_fts.rowid "
            "WHERE memories_fts MATCH ?"
        )
        params = [match]

        if category:
            sql += " AND m.category = ?"
            params.append(category)

        sql += " ORDER BY rank LIMIT ?"
        params.append(int(limit))

        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()

        # bm25() returns negative values; more negative == better.
        return [(Memory.from_row(row), -float(row["rank"])) for row in rows]

    def _search_like(self, query, limit, category):
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9_]+", str(query or "").lower())
            if len(token) >= 2 and token not in _STOPWORDS
        ]
        if not tokens:
            return []

        clauses = []
        params = []
        for token in tokens[:8]:
            clauses.append(
                "(content LIKE ? OR summary LIKE ? OR subject LIKE ? OR tags LIKE ?)"
            )
            params.extend([f"%{token}%"] * 4)

        sql = "SELECT * FROM memories WHERE " + " OR ".join(clauses)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))

        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()

        results = []
        for row in rows:
            memory = Memory.from_row(row)
            haystack = f"{memory.content} {memory.summary} {memory.subject or ''}".lower()
            hits = sum(1 for token in tokens if token in haystack)
            results.append((memory, float(hits)))
        return results

    def count(self, category=None):
        with closing(self._connect()) as connection:
            if category:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM memories WHERE category = ?",
                    (category,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM memories"
                ).fetchone()
        return int(row["n"])

    def counts_by_category(self):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT category, COUNT(*) AS n FROM memories GROUP BY category"
            ).fetchall()
        return {row["category"]: int(row["n"]) for row in rows}

    def distinct_subjects(self, category="project"):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT subject FROM memories "
                "WHERE category = ? AND subject IS NOT NULL AND subject != ''",
                (category,),
            ).fetchall()
        return [row["subject"] for row in rows]

    def export(self):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY id"
            ).fetchall()
        return [Memory.from_row(row).to_dict() for row in rows]

    # ------------------------------------------------------------------
    # Settings (stored in the same database, so they persist too)
    # ------------------------------------------------------------------
    def get_setting(self, key, default=None):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM memory_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self._lock:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO memory_meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
                connection.commit()

    def all_settings(self):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT key, value FROM memory_meta"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}
