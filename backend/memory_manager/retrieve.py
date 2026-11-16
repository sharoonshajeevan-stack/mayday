# ============================================================================
# MAYDAY OS - MEMORY RETRIEVAL
# File: backend/memory_manager/retrieve.py
# Purpose: Pick the *relevant* memories for the current request.
#
# The goal is to hand the model a handful of useful facts - never the whole
# database. Ranking blends keyword relevance (SQLite FTS5/bm25) with the
# record's own metadata: confidence, importance, recency and whether the user
# pinned it. Project memories are isolated so two unrelated projects never get
# mixed together.
# ============================================================================

import math
import re
from datetime import datetime, timezone

from .models import GLOBAL_CATEGORIES

MIN_SCORE = 0.25
DEFAULT_LIMIT = 6
CONTEXT_CHAR_BUDGET = 1400

# Words that carry no retrieval signal. Dropping them stops a query like
# "quantum tunnelling in bananas" from matching every memory containing "in".
STOPWORDS = {
    "the", "and", "for", "you", "your", "yours", "with", "that", "this", "these",
    "those", "have", "has", "had", "are", "was", "were", "but", "not", "can",
    "could", "would", "should", "shall", "what", "when", "where", "which", "how",
    "why", "who", "whom", "about", "into", "from", "they", "them", "then", "than",
    "there", "here", "just", "like", "want", "need", "make", "made", "get", "got",
    "use", "used", "using", "please", "will", "been", "being", "does", "did",
    "doing", "its", "let", "sure", "okay", "yeah", "well", "now", "also", "our",
    "ours", "his", "her", "hers", "him", "she", "it", "is", "am", "be", "been",
    "do", "of", "to", "in", "on", "at", "or", "as", "an", "a", "i", "we", "me",
    "my", "mine", "us", "tell", "give", "show", "know", "think", "some", "any",
    "all", "one", "two", "more", "most", "much", "very", "really", "still",
}


def tokenize(text, min_len=3):
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) >= min_len and token not in STOPWORDS
    ]


def _age_days(timestamp):
    try:
        then = datetime.fromisoformat(str(timestamp))
    except (TypeError, ValueError):
        return 365.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - then
    return max(0.0, delta.total_seconds() / 86400.0)


def _recency_bonus(memory):
    return 0.12 * math.exp(-_age_days(memory.updated_at) / 90.0)


def _haystack_tokens(memory):
    return set(
        tokenize(
            " ".join(
                [
                    memory.content,
                    memory.summary,
                    memory.subject or "",
                    " ".join(memory.tags),
                ]
            )
        )
    )


def overlap(memory, tokens):
    """Fraction of the query's meaningful tokens present in the memory."""
    if not tokens:
        return 0.0
    return len(tokens & _haystack_tokens(memory)) / float(len(tokens))


def score_memory(memory, tokens, rank=None):
    """Blend relevance with the record's metadata into one score."""
    keyword_overlap = overlap(memory, tokens)

    # ``rank`` is a positive relevance score (larger is a better match), so it
    # is squashed into 0..1 while staying monotonic.
    if rank is None:
        bm25 = 0.0
    else:
        rank = max(0.0, float(rank))
        bm25 = rank / (rank + 5.0)

    score = 0.5 * keyword_overlap + 0.22 * bm25
    score += 0.16 * memory.confidence
    score += 0.015 * memory.importance
    score += _recency_bonus(memory)

    if memory.pinned:
        score += 0.25

    return score


def _project_filter(memories, query, store):
    """Keep only one project's memories unless the query names a project."""
    query_low = str(query or "").lower()
    named = [
        subject
        for subject in store.distinct_subjects()
        if subject and subject.lower() in query_low
    ]

    project_items = [m for m in memories if m.category == "project"]

    if not project_items:
        return memories

    if named:
        keep = {subject.lower() for subject in named}
        allowed = [
            m for m in project_items if (m.subject or "").lower() in keep
        ]
    else:
        # No project named: keep only the most recently touched project.
        newest = max(project_items, key=lambda m: m.updated_at or "")
        allowed = [
            m
            for m in project_items
            if (m.subject or "").lower() == (newest.subject or "").lower()
        ]

    allowed_ids = {id(m) for m in allowed}
    return [
        m
        for m in memories
        if m.category != "project" or id(m) in allowed_ids
    ]


def retrieve(query, store, limit=DEFAULT_LIMIT, categories=None, min_score=MIN_SCORE):
    """Return the most relevant memories for ``query`` (best first)."""
    query = str(query or "").strip()
    tokens = set(tokenize(query))

    if not query:
        rows = store.list(limit=limit, order="importance")
        return [memory for memory in rows if memory.pinned or memory.importance >= 8]

    # A query made only of stopwords ("what is it") carries no signal.
    if not tokens:
        return [m for m in store.list(limit=limit, order="importance") if m.pinned]

    raw = store.search(query, limit=max(limit * 8, 40), category=None)

    scored = []
    for memory, rank in raw:
        if categories and memory.category not in categories:
            continue
        # A candidate must share at least one meaningful keyword, unless the
        # user pinned it. Metadata alone must never surface a memory.
        if overlap(memory, tokens) == 0.0 and not memory.pinned:
            continue
        score = score_memory(memory, tokens, rank)
        if score >= min_score:
            scored.append((score, memory))

    # Pinned memories are always candidates, even when they do not match.
    if len(scored) < limit:
        pinned = [m for m in store.list(limit=40, order="importance") if m.pinned]
        for memory in pinned:
            if categories and memory.category not in categories:
                continue
            if any(memory.id == existing.id for _, existing in scored):
                continue
            scored.append((score_memory(memory, tokens), memory))

    scored.sort(key=lambda item: item[0], reverse=True)
    memories = [memory for _, memory in scored]

    memories = _project_filter(memories, query, store)
    return memories[:limit]


def format_context(memories, max_chars=CONTEXT_CHAR_BUDGET):
    """Render memories as a compact block for the model's context."""
    if not memories:
        return ""

    lines = ["[Long-term memory about the user]"]
    used = len(lines[0])

    for memory in memories:
        text = memory.summary or memory.content
        line = f"- ({memory.category}) {text}"

        if used + len(line) > max_chars:
            break

        lines.append(line)
        used += len(line) + 1

    if len(lines) == 1:
        return ""

    lines.append("Use these only if relevant. Do not invent memories.")
    return "\n".join(lines)


def is_global(memory):
    return memory.category in GLOBAL_CATEGORIES
