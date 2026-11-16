# ============================================================================
# MAYDAY OS - MEMORY COMMANDS
# File: backend/memory_manager/commands.py
# Purpose: Let the user talk to the memory database directly.
#
# "Remember this", "forget that", "what do you remember about me",
# "show my project memories", "update my project memory" and
# "don't remember this conversation" all land here and operate on the real
# persistent database - never on a temporary context.
# ============================================================================

import re
from datetime import datetime

from .manager import memory_manager

_REFERENT = r"(?:this|that|it|this information|that information|this one|that one)"

_REMEMBER = re.compile(
    rf"^(?:please\s+|can you\s+|could you\s+)?"
    rf"(?:remember|save|store|note)\s+{_REFERENT}\s*(?:information|details)?\s*[.!]?$",
    re.I,
)

_FORGET_REFERENT = re.compile(
    rf"^(?:please\s+)?(?:forget|delete|remove)\s+{_REFERENT}"
    rf"\s*(?:information|memory|details)?\s*[.!]?$",
    re.I,
)

_FORGET_ABOUT = re.compile(
    r"^(?:please\s+)?(?:forget|delete|remove)\s+about\s+(?P<q>.+?)\s*[.!]?$",
    re.I,
)

_FORGET_MEMORY = re.compile(
    r"^(?:please\s+)?(?:forget|delete|remove)\s+"
    r"(?:the\s+|my\s+|that\s+|this\s+)?"
    r"(?P<q>[^.!?]*?memor(?:y|ies)[^.!?]*?)\s*[.!]?$",
    re.I,
)

# Category words a "forget my ... memory" phrase may name.
_CATEGORY_WORDS = {
    "project": "project",
    "projects": "project",
    "preference": "preference",
    "preferences": "preference",
    "technical": "technical",
    "task": "task",
    "tasks": "task",
    "user": "user",
    "conversation": "conversation",
    "conversations": "conversation",
}


def _category_in(text):
    low = str(text or "").lower()
    for word, category in _CATEGORY_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return category
    return None

_ABOUT_ME = re.compile(
    r"(?:what\s+do\s+you\s+(?:remember|know)\s+about\s+me|"
    r"what\s+do\s+you\s+remember|my\s+memories|list\s+my\s+memories)",
    re.I,
)

_SHOW_CATEGORY = re.compile(
    r"(?:show|list|what\s+are)\s+(?:me\s+)?(?:my\s+|the\s+)?"
    r"(?P<what>project|preference|technical|task|user|conversation)\s+memor(?:y|ies)",
    re.I,
)

_UPDATE_PROJECT = re.compile(
    r"^update\s+(?:my\s+|the\s+)?project\s+memor(?:y|ies)\s*(?P<rest>.*)$",
    re.I,
)

_DONT_REMEMBER = re.compile(
    r"^(?:please\s+)?(?:don't|do not|dont)\s+remember\s+(?:this|the|our)\s+"
    r"(?:conversation|chat|session)\s*[.!]?$",
    re.I,
)

_WORKING_ON = re.compile(
    r"(?:what\s+was\s+i\s+working\s+on|what\s+am\s+i\s+working\s+on|"
    r"what\s+is\s+my\s+current\s+project|my\s+current\s+project)",
    re.I,
)

_CLEAR_REQUEST = re.compile(
    r"^(?:please\s+)?(?:clear|delete|erase|wipe)\s+(?:all\s+|my\s+|the\s+)?"
    r"memor(?:y|ies)\s*[.!]?$",
    re.I,
)

_CLEAR_CONFIRM = re.compile(
    r"^(?:yes\s+)?confirm\s+(?:clear|delete|erase|wipe)\s+"
    r"(?:all\s+|my\s+|the\s+)?memor(?:y|ies)\s*[.!]?$",
    re.I,
)


def _reply(response, spoken=None, action=None, extra=None):
    result = {
        "status": "success",
        "source": "memory",
        "kind": "memory",
        "response": response,
        "spoken": spoken or response,
        "timestamp": datetime.now().isoformat(),
    }
    if action:
        result["action"] = action
    if extra:
        result.update(extra)
    return result


def _list_lines(memories, limit=8):
    lines = []
    for memory in memories[:limit]:
        text = memory.get("summary") or memory.get("content") or ""
        lines.append(f"[{memory.get('category')}] {text}")
    return lines


def handle_memory_command(text):
    """Return a reply dict when ``text`` is a memory command, else None."""
    command = str(text or "").strip()
    if not command:
        return None

    # 1. "don't remember this conversation" ---------------------------------
    if _DONT_REMEMBER.match(command):
        memory_manager.ignore_conversation()
        return _reply(
            "Understood - I'll stop remembering this conversation and I've "
            "dropped what I captured from it.",
            "Understood. I won't remember this conversation.",
            action="memory_ignore",
        )

    # 2. "confirm clear memories" -------------------------------------------
    if _CLEAR_CONFIRM.match(command):
        removed = memory_manager.clear()
        return _reply(
            f"Done - cleared {removed} memories from the database.",
            "Done. Memory cleared.",
            action="memory_clear",
            extra={"removed": removed},
        )

    # 3. "clear my memories" (needs confirmation) ---------------------------
    if _CLEAR_REQUEST.match(command):
        return _reply(
            "That deletes every long-term memory. Say \"confirm clear memories\" "
            "to go ahead.",
            "That wipes everything. Say confirm clear memories to proceed.",
            action="memory_clear_pending",
        )

    # 4. "remember this" ----------------------------------------------------
    if _REMEMBER.match(command):
        result = memory_manager.remember_last_exchange()
        if result is None:
            return _reply(
                "There's nothing in this conversation to save yet.",
                "Nothing to save yet.",
            )
        content = (result.get("memory") or {}).get("summary") or ""
        return _reply(
            f"Saved that: {content}",
            "Saved.",
            action="memory_save",
            extra={"memory": result.get("memory")},
        )

    # 5. "forget that information" -----------------------------------------
    if _FORGET_REFERENT.match(command):
        removed = memory_manager.forget_latest()
        if not removed:
            return _reply("I don't have anything recent to forget.")
        return _reply(
            f"Forgotten: {removed.get('summary') or removed.get('content')}",
            "Forgotten.",
            action="memory_forget",
            extra={"memory": removed},
        )

    # 6. "forget about X" / "forget my project memory" ----------------------
    # Deliberately narrow: a bare "delete the file" is a system/AI request, not
    # a memory command, so it falls through to the router below.
    forget = _FORGET_ABOUT.match(command) or _FORGET_MEMORY.match(command)
    if forget:
        query = (forget.group("q") or "").strip()
        category = _category_in(query)

        if category:
            candidates = memory_manager.list(category=category, limit=1)
            removed = []
            if candidates and memory_manager.delete_memory(candidates[0]["id"]):
                removed = candidates
        else:
            removed = memory_manager.delete_matching(query)

        if not removed:
            return _reply(
                f"I don't have anything stored about {query or 'that'}.",
                f"Nothing stored about {query or 'that'}.",
            )

        return _reply(
            f"Forgotten {len(removed)} memory item(s) about {query}.",
            "Forgotten.",
            action="memory_forget",
            extra={"removed": removed},
        )

    # 7. "update my project memory" ----------------------------------------
    update = _UPDATE_PROJECT.match(command)
    if update:
        rest = (update.group("rest") or "").strip(" :,-")
        if rest:
            result = memory_manager.remember(
                rest,
                category="project",
                key="project:progress",
                confidence=0.9,
                importance=8,
                source="explicit",
                tags=["progress"],
            )
            return _reply(
                f"Project memory updated: {rest}",
                "Project memory updated.",
                action="memory_update",
                extra={"memory": result.get("memory")},
            )

        current = memory_manager.list(category="project", limit=6)
        if not current:
            return _reply(
                "I don't have any project memory yet. Tell me what you're "
                "working on and I'll start one.",
                "No project memory yet.",
            )
        lines = _list_lines(current)
        return _reply(
            "Here's your current project memory:\n" + "\n".join(lines)
            + "\n\nTell me \"update my project memory to ...\" to change it.",
            "Here's what I have on your project.",
            extra={"memories": current},
        )

    # 8. "show my project memories" ----------------------------------------
    show = _SHOW_CATEGORY.search(command)
    if show:
        category = show.group("what").lower()
        memories = memory_manager.list(category=category, limit=20)
        if not memories:
            return _reply(
                f"I don't have any {category} memories yet.",
                f"No {category} memories yet.",
            )
        lines = _list_lines(memories, limit=12)
        return _reply(
            f"Here are your {category} memories:\n" + "\n".join(lines),
            f"Here are your {category} memories.",
            extra={"memories": memories},
        )

    # 9. "what do you remember about me" -----------------------------------
    if _ABOUT_ME.search(command):
        memories = (
            memory_manager.list(category="preference", limit=10)
            + memory_manager.list(category="user", limit=10)
        )
        if not memories:
            return _reply(
                "I don't have any personal memories yet. Say \"remember that ...\" "
                "and I'll keep it.",
                "Nothing about you saved yet.",
            )
        lines = _list_lines(memories, limit=12)
        return _reply(
            "Here's what I remember about you:\n" + "\n".join(lines),
            "Here's what I remember about you.",
            extra={"memories": memories},
        )

    # 10. "what was I working on" ------------------------------------------
    if _WORKING_ON.search(command):
        projects = memory_manager.list(category="project", limit=8)
        tasks = memory_manager.list(category="task", limit=8)
        if not projects and not tasks:
            return _reply(
                "I don't have a project on record yet.",
                "Nothing on record yet.",
            )
        lines = _list_lines(projects + tasks, limit=10)
        return _reply(
            "Here's what you were working on:\n" + "\n".join(lines),
            "Here's what you were working on.",
            extra={"memories": projects + tasks},
        )

    return None
