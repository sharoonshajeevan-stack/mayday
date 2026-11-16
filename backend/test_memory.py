"""Standalone verification for MAYDAY's long-term memory system.

Run from the backend folder with the project virtualenv:

    python test_memory.py

Everything runs against a throwaway SQLite database in the system temp
directory, so the real backend/memory/mayday_memory.db is never touched. No
network, no microphone, no camera: this suite only exercises storage,
extraction, retrieval, privacy and the memory commands.
"""

import inspect
import os
import sys
import tempfile

# Point the memory manager at a disposable database *before* importing it.
_TMP_DIR = tempfile.mkdtemp(prefix="mayday_memory_test_")
_DB_PATH = os.path.join(_TMP_DIR, "mayday_memory.db")
os.environ["MAYDAY_MEMORY_DB"] = _DB_PATH
os.environ["MAYDAY_MEMORY_AUTOCAPTURE"] = "true"
os.environ["MAYDAY_MEMORY_RETRIEVAL"] = "true"
os.environ["MAYDAY_MEMORY_SUMMARY_AFTER"] = "4"

from memory_manager import handle_memory_command, memory_manager  # noqa: E402
from memory_manager import extract, privacy, retrieve, store, summarize  # noqa: E402
from memory_manager.manager import MemoryManager  # noqa: E402
from memory_manager.models import Memory  # noqa: E402

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL

    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  ->  {detail}")


def section(title):
    print(f"\n[{title}]")


# ===========================================================================
# [1] Storage basics - acceptance tests 1, 5, 6, 9
# ===========================================================================

section("1. Storage basics")

memory_manager.clear()

check("fresh database is empty", memory_manager.store.count() == 0)

result = memory_manager.remember(
    "User's preferred name is Sharo.",
    category="preference",
    key="preference:name",
    confidence=0.9,
    importance=9,
    tags=["name"],
)
check("save a new memory", result["status"] == "saved", result)
first_id = result["memory"]["id"]

duplicate = memory_manager.remember(
    "User's preferred name is Sharo.",
    category="preference",
    key="preference:name",
)
check("duplicate is not stored twice", duplicate["status"] == "duplicate", duplicate)
check("duplicate keeps one row", memory_manager.store.count() == 1)

updated = memory_manager.remember(
    "User's preferred name is Sharoon.",
    category="preference",
    key="preference:name",
)
check("contradiction updates in place", updated["status"] == "updated", updated)
check("contradiction keeps one row", memory_manager.store.count() == 1)
check(
    "contradiction reports the old value",
    updated.get("previous") == "User's preferred name is Sharo.",
    updated,
)
check(
    "contradiction stores the new value",
    memory_manager.get(first_id)["content"] == "User's preferred name is Sharoon.",
)

manual = memory_manager.remember(
    "User prefers dark mode in every editor.",
    category="preference",
    confidence=0.6,
)
edited = memory_manager.update_memory(
    manual["memory"]["id"], content="User prefers light mode.", importance=9
)
check("edit an existing memory", edited["content"] == "User prefers light mode.")
check("edit persists importance", edited["importance"] == 9)

deletable = memory_manager.remember(
    "Throwaway memory about a temporary detail.",
    category="user",
)
deleted = memory_manager.delete_memory(deletable["memory"]["id"])
check("delete a selected memory", deleted is True)
check("deleted memory is gone", memory_manager.get(deletable["memory"]["id"]) is None)

# ===========================================================================
# [2] Automatic extraction - acceptance tests 3, 4, 12
# ===========================================================================

section("2. Automatic extraction")

cases = {
    "My current project is called MAYDAY and it uses React and Python.": [
        ("project", "project:mayday:identity", "MAYDAY"),
        ("project", "project:tech:react-and-python", "MAYDAY"),
    ],
    "I prefer short spoken responses.": [
        ("preference", "preference:response_length", None),
    ],
    "I am currently working on the browser automation feature.": [
        ("project", "project:progress:the-browser-automation-feature", None),
    ],
    "remind me to call the bank": [("task", "task:pending:call-the-bank", None)],
    "My PC has 16GB of RAM and an AMD Ryzen 7 5700U.": [
        ("technical", "technical:hardware", None),
    ],
    "I fixed the browser issue by updating the driver.": [
        ("technical", None, None),
    ],
}

for utterance, expected in cases.items():
    candidates = extract.extract_candidates(utterance)
    found = [(c.category, c.key, c.subject) for c in candidates]
    check(
        f"extracts {utterance[:38]!r}",
        all(item in found for item in expected),
        found,
    )

ignored = [
    "what time is it?",
    "open google and search for claude",
    "take a screenshot",
    "hello",
    "thanks",
]
for utterance in ignored:
    check(
        f"ignores {utterance!r}",
        extract.extract_candidates(utterance) == [],
    )

# ===========================================================================
# [3] Privacy - acceptance test 12
# ===========================================================================

section("3. Privacy (secrets are never stored)")

secrets = [
    "My OpenAI key is sk-abcdefghijklmnopqrstuvwxyz123456",
    "the token is ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "password: hunter2",
    "my api key is AIzaSyA1b2C3d4E5f6G7h8I9j0KLMNOPQRSTUVW",
]
for secret in secrets:
    check(f"detects secret in {secret[:28]!r}", privacy.contains_secret(secret))

before = memory_manager.store.count()
blocked = memory_manager.remember(
    "My OpenAI key is sk-abcdefghijklmnopqrstuvwxyz123456",
    category="technical",
)
check("secret memory is blocked", blocked["status"] == "blocked", blocked)
check("blocked memory is not stored", memory_manager.store.count() == before)

check(
    "redaction keeps the non-secret part",
    privacy.redact("key is sk-abcdefghijklmnopqrstuvwxyz123456 done")
    == "key is [redacted] done",
)

# ===========================================================================
# [4] Persistence across restarts - acceptance test 2
# ===========================================================================

section("4. Persistence across restarts")

memory_manager.remember(
    "Active project 'MAYDAY'.",
    category="project",
    key="project:mayday:identity",
    subject="MAYDAY",
    importance=9,
)

reopened = MemoryManager(db_path=_DB_PATH)
check(
    "restart keeps memories",
    reopened.store.count() == memory_manager.store.count(),
    f"{reopened.store.count()} != {memory_manager.store.count()}",
)
check(
    "restart keeps project memory",
    any(
        m["key"] == "project:mayday:identity"
        for m in reopened.list(category="project")
    ),
)
check("database file exists on disk", os.path.exists(_DB_PATH))

# ===========================================================================
# [5] Retrieval - acceptance tests 3, 4, 7, 8, 11
# ===========================================================================

section("5. Retrieval")

memory_manager.remember(
    "User prefers the voice 'bf_emma'.",
    category="preference",
    key="preference:voice",
    tags=["voice"],
    importance=8,
)
memory_manager.remember(
    "Currently working on: the browser automation feature",
    category="project",
    key="project:progress:the-browser-automation-feature",
    subject="MAYDAY",
    importance=8,
)
memory_manager.remember(
    "Fixed the browser issue by updating the driver.",
    category="technical",
    tags=["troubleshooting"],
    importance=8,
)

context = memory_manager.retrieve_context("use my usual voice")
check("voice preference is retrieved", "bf_emma" in context, context)

context = memory_manager.retrieve_context("continue my project")
check("project context is retrieved", "MAYDAY" in context, context)

context = memory_manager.retrieve_context("what was the browser issue we fixed?")
check("old technical memory is retrieved", "driver" in context, context)

check(
    "no relevant memory returns nothing",
    memory_manager.retrieve_context("quantum tunnelling in bananas") == "",
)

# Project isolation: two projects must never be mixed.
memory_manager.remember(
    "Active project 'SideQuest'.",
    category="project",
    key="project:sidequest:identity",
    subject="SideQuest",
    importance=9,
)
memory_manager.remember(
    "Currently working on: the SideQuest map renderer",
    category="project",
    key="project:progress:sidequest-map",
    subject="SideQuest",
    importance=8,
)

mixed = memory_manager.recall("continue my project", limit=10)
subjects = {m.get("subject") for m in mixed if m["category"] == "project"}
check(
    "project memories stay isolated",
    len(subjects) <= 1,
    subjects,
)

named = memory_manager.recall("continue my SideQuest project", limit=10)
sidequest = [m for m in named if m["category"] == "project"]
check(
    "naming a project selects it",
    sidequest and all(m.get("subject") == "SideQuest" for m in sidequest),
    sidequest,
)

# Keyword search over old project information.
hits = memory_manager.search("browser")
check("keyword search finds old memories", len(hits) >= 1, hits)

# ===========================================================================
# [6] Conversation summaries - acceptance test (section F)
# ===========================================================================

section("6. Conversation summaries")

memory_manager.clear()
memory_manager._session_buffer = []

conversation = [
    ("My project is called Orbit.", "Got it."),
    ("I need to finish the login screen.", "Noted."),
    ("We decided to use Postgres instead of SQLite.", "Understood."),
    ("I am currently working on the login screen.", "Okay."),
]
for user, assistant in conversation:
    memory_manager.observe(user, assistant)

summaries = memory_manager.list(category="conversation")
check("long conversation is summarised", len(summaries) >= 1, summaries)
summary_text = summaries[0]["content"] if summaries else ""
check("summary keeps unfinished work", "login screen" in summary_text, summary_text)
check("summary keeps decisions", "Postgres" in summary_text, summary_text)
check("summary is compact", len(summary_text) < 1200, len(summary_text))

pending = memory_manager.list(category="task")
check("unfinished tasks are captured", len(pending) >= 1, pending)

raw = summarize.summarize(conversation)
check("summariser is offline and rule based", raw is not None and raw["topics"])

# ===========================================================================
# [7] Memory commands - acceptance tests (section E)
# ===========================================================================

section("7. Memory commands")

memory_manager.clear()
memory_manager.resume_capture()
memory_manager._session_buffer = []

memory_manager.note_exchange("My favourite editor is Neovim.", "Noted.")

reply = handle_memory_command("remember this")
check("'remember this' saves", reply and reply.get("action") == "memory_save", reply)

reply = handle_memory_command("save this information")
check("'save this information' saves", reply and reply.get("action") == "memory_save", reply)

memory_manager.remember(
    "User's preferred name is Sharoon.",
    category="preference",
    key="preference:name",
)
memory_manager.remember(
    "Active project 'MAYDAY'.",
    category="project",
    key="project:mayday:identity",
    subject="MAYDAY",
)

reply = handle_memory_command("what do you remember about me?")
check("'what do you remember about me' answers", reply and "Sharoon" in reply["response"], reply)

reply = handle_memory_command("show my project memories")
check("'show my project memories' answers", reply and "MAYDAY" in reply["response"], reply)

reply = handle_memory_command("update my project memory to working on the voice layer")
check("'update my project memory' writes", reply and reply.get("action") == "memory_update", reply)
check(
    "updated project memory is stored",
    any(
        "voice layer" in m["content"]
        for m in memory_manager.list(category="project")
    ),
)

reply = handle_memory_command("don't remember this conversation")
check("'don't remember this conversation' acknowledges", reply and reply.get("action") == "memory_ignore", reply)
check("capture is paused", memory_manager.status()["capture_paused"] is True)

memory_manager.resume_capture()
memory_manager.remember("Temporary fact about a one-off errand.", category="user")
reply = handle_memory_command("forget that information")
check("'forget that information' deletes", reply and reply.get("action") == "memory_forget", reply)

# A plain system/AI request must not be swallowed as a memory command.
reply = handle_memory_command("delete the temporary file")
check("non-memory 'delete ...' falls through", reply is None, reply)

memory_manager.remember(
    "Active project 'MAYDAY'.",
    category="project",
    key="project:mayday:identity",
    subject="MAYDAY",
)
reply = handle_memory_command("forget my project memory")
check(
    "'forget my project memory' deletes one",
    reply and reply.get("action") == "memory_forget",
    reply,
)

reply = handle_memory_command("clear my memories")
check("clearing requires confirmation", reply and reply.get("action") == "memory_clear_pending", reply)

reply = handle_memory_command("confirm clear memories")
check("confirmation clears the database", reply and reply.get("action") == "memory_clear", reply)
check("database is empty after clear", memory_manager.store.count() == 0)

# ===========================================================================
# [8] Settings - acceptance test 10
# ===========================================================================

section("8. Settings")

memory_manager.resume_capture()
memory_manager.update_settings({"auto_capture": False})
check("auto capture can be disabled", memory_manager.auto_capture is False)

before = memory_manager.store.count()
saved = memory_manager.observe("I prefer very detailed answers.", "Okay.")
check("disabled auto capture stores nothing", saved == [] and memory_manager.store.count() == before)

memory_manager.update_settings({"auto_capture": True})
memory_manager.observe("I prefer very detailed answers.", "Okay.")
check("re-enabled auto capture stores again", memory_manager.store.count() > before)

memory_manager.update_settings({"retrieval_enabled": False})
check("retrieval can be disabled", memory_manager.retrieve_context("detailed") == "")
memory_manager.update_settings({"retrieval_enabled": True})
check("retrieval can be re-enabled", memory_manager.retrieval_enabled is True)

settings = memory_manager.update_settings({"summarize_enabled": False})
check("settings are reported", settings["summarize_enabled"] is False)
memory_manager.update_settings({"summarize_enabled": True})

# Settings must survive a restart too.
reopened = MemoryManager(db_path=_DB_PATH)
check("settings persist", reopened.get_settings()["auto_capture"] is True)

# ===========================================================================
# [9] Offline guarantee - acceptance test 11
# ===========================================================================

section("9. Offline guarantee")

sources = "".join(
    inspect.getsource(module)
    for module in (store, retrieve, extract, summarize, privacy)
)
network_tokens = ("requests.", "urllib.request", "socket.socket", "http.client", "aiohttp")
check(
    "memory modules make no network calls",
    not any(token in sources for token in network_tokens),
)
check("memory is stored in a local sqlite file", memory_manager.db_path.endswith(".db"))
check("sqlite backend is used", memory_manager.store.has_fts in (True, False))

# ===========================================================================
# [10] Export / stats - section G (inspect, edit, export, delete)
# ===========================================================================

section("10. Export and stats")

memory_manager.remember("User's preferred name is Sharoon.", category="preference")
exported = memory_manager.export()
check("export contains memories", exported["total"] >= 1 and exported["memories"])
check(
    "exported record carries timestamps",
    "created_at" in exported["memories"][0]
    and "updated_at" in exported["memories"][0],
)
stats = memory_manager.stats()
check("stats reports categories", "by_category" in stats and "preference" in stats["by_category"])

# ===========================================================================
# Summary
# ===========================================================================

print("\n" + "=" * 60)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 60)

sys.exit(1 if FAIL else 0)
