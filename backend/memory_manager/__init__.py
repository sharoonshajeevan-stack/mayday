# ============================================================================
# MAYDAY OS - LONG-TERM MEMORY
# File: backend/memory_manager/__init__.py
# Purpose: Public surface of the modular long-term memory manager.
#
# Everything the rest of MAYDAY needs is exported here:
#
#     from memory_manager import (
#         memory_manager, remember, recall, retrieve_context,
#         handle_memory_command,
#     )
#
# The package owns a local SQLite database (backend/memory/mayday_memory.db).
# It works fully offline, survives restarts and reboots, and never stores raw
# audio/video or credentials.
# ============================================================================

# Best-effort: make sure backend/.env is loaded before the manager reads its
# configuration, no matter which module imported us first. python-dotenv is an
# existing project dependency, but the memory package stays usable without it.
try:  # pragma: no cover - trivial environment bootstrap
    from pathlib import Path as _Path

    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_Path(__file__).resolve().parent.parent / ".env", override=False)
except Exception:  # noqa: BLE001 - memory must work without dotenv
    pass

from .commands import handle_memory_command
from .manager import MemoryManager, memory_manager
from .models import CATEGORIES, DEFAULT_CATEGORY, Memory

__all__ = [
    "CATEGORIES",
    "DEFAULT_CATEGORY",
    "Memory",
    "MemoryManager",
    "memory_manager",
    "handle_memory_command",
    "remember",
    "observe",
    "retrieve_context",
    "recall",
    "search",
    "list_memories",
    "get_settings",
    "update_settings",
    "stats",
    "export",
]


def remember(content, **kwargs):
    """Store one long-term memory (de-duplicated, credential-safe)."""
    return memory_manager.remember(content, **kwargs)


def observe(user_text, assistant_text=""):
    """Auto-extract anything worth remembering from an exchange."""
    return memory_manager.observe(user_text, assistant_text)


def retrieve_context(query, limit=6):
    """Return a compact memory block to add to the model's context."""
    return memory_manager.retrieve_context(query, limit=limit)


def recall(query, limit=6):
    """Return the memories relevant to ``query`` as plain dictionaries."""
    return memory_manager.recall(query, limit=limit)


def search(query, limit=20, category=None):
    return memory_manager.search(query, limit=limit, category=category)


def list_memories(category=None, limit=200, offset=0, order="updated", query=None):
    return memory_manager.list(
        category=category, limit=limit, offset=offset, order=order, query=query
    )


def get_settings():
    return memory_manager.get_settings()


def update_settings(patch):
    return memory_manager.update_settings(patch)


def stats():
    return memory_manager.stats()


def export():
    return memory_manager.export()
