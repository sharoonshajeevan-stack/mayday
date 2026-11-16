"""Standalone verification for MAYDAY's personality layer.

Run from the backend folder with the project virtualenv:

    python test_personality.py

It never launches a real app: the command router's executors are replaced with
stubs, so the whole run is safe and fast.
"""

import os
import sys
import tempfile

# Use a throwaway settings file so the real backend/personality.json is never
# touched by the test run.
_TMP_DIR = tempfile.mkdtemp(prefix="mayday_personality_")
os.environ["MAYDAY_PERSONALITY_FILE"] = os.path.join(_TMP_DIR, "personality.json")
# Keep the test run out of the real long-term memory database.
os.environ["MAYDAY_MEMORY_DB"] = os.path.join(_TMP_DIR, "memory.db")

import personality  # noqa: E402
import command_router  # noqa: E402
import ai_engine  # noqa: E402
from action_result import format_action_result  # noqa: E402

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


# ---------------------------------------------------------------------------
# Stub the command router executors (never launch anything for real).
# ---------------------------------------------------------------------------

def fake_open_url(url):
    return {"status": "success", "url": url, "message": f"Opening {url}"}


def fake_open_uri(uri, label=None):
    return {"status": "success", "uri": uri, "message": f"Opening {label or uri}"}


def fake_launch_app(app):
    if app not in {"notepad", "spotify", "vs code", "calculator", "chrome", "code"}:
        return {"status": "error", "message": f"Could not find {app}"}
    return {"status": "success", "application": app, "message": f"Launched {app}"}


def fake_screenshot():
    return {
        "status": "success",
        "message": "Screenshot saved to screenshots/mayday.png",
        "path": "screenshots/mayday.png",
    }


def fake_open_folder(folder):
    return {
        "status": "success",
        "path": f"C:/Users/test/{folder}",
        "message": f"Opened {folder}",
    }


def patch_router():
    command_router.execute_open_url = fake_open_url
    command_router.execute_open_uri = fake_open_uri
    command_router.execute_launch_app = fake_launch_app
    command_router.execute_screenshot = fake_screenshot
    command_router.open_folder = fake_open_folder


patch_router()


def run(command):
    """Replicate main.py's /api/command action handling without Flask."""
    action = command_router.route_command(command)

    if not action:
        return None

    formatted = format_action_result(action)
    base = formatted.get("response") or action.get("message") or "Command completed."

    return {
        "action": action,
        "formatted": formatted,
        "commentary": personality.comment_on_action(
            action, command, base_message=base
        ),
    }


def reset_cooldown():
    personality._config._last_kind_at.clear()
    personality._config._recent_comments.clear()


# ---------------------------------------------------------------------------
# 1. Defaults
# ---------------------------------------------------------------------------

print("\n[1] Defaults")
settings = personality.get_settings()
check("personality_enabled default", settings["personality_enabled"] is True)
check("sarcasm_level default 70", settings["sarcasm_level"] == 70)
check("humour_level default 75", settings["humour_level"] == 75)
check("commentary default balanced", settings["commentary_frequency"] == "balanced")
check("spoken default short", settings["spoken_response_length"] == "short")
check("default voice British", settings["voice"].startswith("bf_"))

# ---------------------------------------------------------------------------
# 2. Persistence + validation
# ---------------------------------------------------------------------------

print("\n[2] Persistence + validation")
personality.update_settings({"sarcasm_level": 25, "commentary_frequency": "minimal"})
check("settings file written", os.path.exists(os.environ["MAYDAY_PERSONALITY_FILE"]))

reloaded = personality.PersonalityConfig(os.environ["MAYDAY_PERSONALITY_FILE"])
check(
    "reload keeps values",
    reloaded.get()["sarcasm_level"] == 25
    and reloaded.get()["commentary_frequency"] == "minimal",
)

check(
    "level clamped to 100",
    personality.update_settings({"sarcasm_level": 999})["sarcasm_level"] == 100,
)
personality.update_settings({"commentary_frequency": "nonsense"})
check(
    "invalid commentary falls back",
    personality.get_settings()["commentary_frequency"] == "balanced",
)

personality.reset_settings()
check("reset restores defaults", personality.get_settings()["sarcasm_level"] == 70)

# ---------------------------------------------------------------------------
# 3. System prompt
# ---------------------------------------------------------------------------

print("\n[3] System prompt")
prompt = personality.build_system_prompt()
check("prompt names MAYDAY", "MAYDAY" in prompt)
check("prompt British voice", "British" in prompt)
check("prompt concise spoken", "short" in prompt.lower())

personality.update_settings({"personality_enabled": False})
check("prompt off notice", "Personality is currently OFF" in personality.build_system_prompt())
personality.reset_settings()

personality.update_settings({"quiet_mode": True})
check("prompt quiet notice", "Quiet mode is ON" in personality.build_system_prompt())
personality.reset_settings()

# ---------------------------------------------------------------------------
# 4. Spoken length
# ---------------------------------------------------------------------------

print("\n[4] Spoken length")
long_reply = "First sentence here. Second sentence follows. Third sentence ends it."
check("short -> first sentence", personality.shorten_for_speech(long_reply, "short") == "First sentence here.")
check("medium -> two sentences", personality.shorten_for_speech(long_reply, "medium") == "First sentence here. Second sentence follows.")
check("detailed -> full", personality.shorten_for_speech(long_reply, "detailed") == long_reply)

personality.update_settings({"quiet_mode": True})
check("quiet forces short", personality.shorten_for_speech(long_reply) == "First sentence here.")
personality.reset_settings()

# ---------------------------------------------------------------------------
# 5. Action classification
# ---------------------------------------------------------------------------

print("\n[5] Action classification")
check("classify app", personality.classify_action({"status": "success", "application": "notepad"}, "open notepad") == "app")
check("classify site", personality.classify_action({"status": "success", "url": "https://youtube.com"}, "open youtube") == "site")
check("classify media (uri)", personality.classify_action({"status": "success", "uri": "spotify:search:x"}, "play x") == "media")
check("classify screenshot", personality.classify_action({"status": "success", "message": "Screenshot saved"}, "screenshot") == "screenshot")
check("classify error", personality.classify_action({"status": "error", "message": "nope"}, "open nope") == "error")
check("classify search", personality.classify_action({"status": "success", "results": []}, "look up x") == "search")
check("classify processes", personality.classify_action({"status": "success", "processes": []}, "show processes") == "processes")

# ---------------------------------------------------------------------------
# 6. Router + commentary scenarios
# ---------------------------------------------------------------------------

print("\n[6] Router + commentary")


def scenario(name, command, expected_kind):
    reset_cooldown()
    out = run(command)

    check(f"{name}: routed", out is not None, command)

    if not out:
        return out

    check(f"{name}: kind == {expected_kind}", out["commentary"]["kind"] == expected_kind, out["commentary"]["kind"])
    check(f"{name}: commented", out["commentary"]["commented"] is True, out["commentary"]["response"])
    check(f"{name}: base kept", bool(out["commentary"]["response"].strip()))
    check(f"{name}: spoken non-empty", bool(out["commentary"]["spoken"].strip()))

    return out


scenario("open YouTube", "open youtube", "site")
scenario("open Spotify", "open spotify", "app")
scenario("play music", "play music", "media")
scenario("open VS Code", "open vs code", "app")
scenario("screenshot", "take a screenshot", "screenshot")

# Failed app launch (app in the alias table returns the error result directly).
reset_cooldown()
command_router.execute_launch_app = lambda app: {"status": "error", "message": f"Could not launch {app}"}
out = run("open notepad")
check("failed launch routed", out is not None)
check("failed launch kind error", out and out["commentary"]["kind"] == "error")
check("failed launch honest", out and "Could not launch" in out["commentary"]["response"], out["commentary"]["response"] if out else None)
command_router.execute_launch_app = fake_launch_app

# Unknown app falls through to the AI (no fabricated success).
check("unknown app falls through", run("open definitelynotrealapp") is None)

# Follow-up context: "open YouTube" then "play Arijit Singh".
reset_cooldown()
run("open youtube")
reset_cooldown()
out = run("play arijit singh")
check("follow-up routed", out is not None)
check("follow-up lands on youtube", out and "youtube" in (out["action"].get("url") or "").lower(), out["action"].get("url") if out else None)
check("follow-up kind media", out and out["commentary"]["kind"] == "media")

# Search follow-up defaults to Google when there is no media context.
reset_cooldown()
command_router._LAST_CONTEXT.update({"kind": None, "name": None, "url": None, "at": 0.0})
out = run("search arijit singh")
check("search defaults google", out and "google" in (out["action"].get("url") or "").lower(), out["action"].get("url") if out else None)

# Router regression: "open google and search for claude" used to be read as an
# app launch ("google and search for claude"), fall through and get handed to
# the AI engine, where a rate limit could leave it stuck in THINKING.
reset_cooldown()
command_router._LAST_CONTEXT.update({"kind": None, "name": None, "url": None, "at": 0.0})
out = run("open google and search for claude")
check("compound search routed", out is not None, "open google and search for claude")
check(
    "compound search lands on google",
    out and "google" in (out["action"].get("url") or "").lower(),
    out["action"].get("url") if out else None,
)
check(
    "compound search keeps the query",
    out and (out["action"].get("message") or "").lower() == "searching google for claude",
    out["action"].get("message") if out else None,
)
check("compound search kind site", out and out["commentary"]["kind"] == "site")

# Router regression: "search for X" used to search Google for "for X".
reset_cooldown()
command_router._LAST_CONTEXT.update({"kind": None, "name": None, "url": None, "at": 0.0})
out = run("search for claude")
check(
    "search-for query is clean",
    out and (out["action"].get("message") or "").lower() == "searching google for claude",
    out["action"].get("message") if out else None,
)

# Router regression: "search google for X" used to search for "google for X".
reset_cooldown()
command_router._LAST_CONTEXT.update({"kind": None, "name": None, "url": None, "at": 0.0})
out = run("search google for claude")
check(
    "search-site-for query is clean",
    out and (out["action"].get("message") or "").lower() == "searching google for claude",
    out["action"].get("message") if out else None,
)

# Repeated commands: first comments, second stays quiet (cooldown).
reset_cooldown()
first = run("open notepad")
second = run("open notepad")
check("repeat #1 commented", first and first["commentary"]["commented"] is True)
check("repeat #2 quiet (cooldown)", second and second["commentary"]["commented"] is False)

# ---------------------------------------------------------------------------
# 7. Quiet mode / disabled / frequency
# ---------------------------------------------------------------------------

print("\n[7] Quiet / disabled / frequency")

personality.update_settings({"quiet_mode": True})
reset_cooldown()
out = run("open notepad")
check("quiet mode: no commentary", out["commentary"]["commented"] is False)
check("quiet mode: base kept", bool(out["commentary"]["response"].strip()))
personality.reset_settings()

personality.update_settings({"personality_enabled": False})
reset_cooldown()
check("disabled: no commentary", run("open notepad")["commentary"]["commented"] is False)
personality.reset_settings()

personality.update_settings({"commentary_frequency": "off"})
reset_cooldown()
check("frequency off: no commentary", run("open notepad")["commentary"]["commented"] is False)
personality.reset_settings()

personality.update_settings({"commentary_frequency": "minimal"})
reset_cooldown()
check("minimal: app suppressed", run("open notepad")["commentary"]["commented"] is False)
reset_cooldown()
command_router.execute_launch_app = lambda app: {"status": "error", "message": "nope"}
check("minimal: error kept", run("open notepad")["commentary"]["commented"] is True)
command_router.execute_launch_app = fake_launch_app
personality.reset_settings()

# ---------------------------------------------------------------------------
# 8. AI engine: history + prompt + spoken shortening
# ---------------------------------------------------------------------------

print("\n[8] AI engine wiring")

ai_engine.get_recent_memories = lambda limit=6: [
    {"user_input": "open youtube", "ai_response": "Opening YouTube."},
]

engine = ai_engine.AIEngine()
messages = engine._conversation_messages("play arijit singh")
check("history has prior user", {"role": "user", "content": "open youtube"} in messages)
check("history has prior assistant", {"role": "assistant", "content": "Opening YouTube."} in messages)
check("history ends with new command", messages[-1]["content"] == "play arijit singh")

captured = {}


def fake_online(prompt, system_prompt=None, messages=None):
    captured["prompt"] = prompt
    captured["system_prompt"] = system_prompt
    captured["messages"] = messages
    return {"status": "success", "response": "Sure thing.", "source": "gemini"}


ai_engine.generate_online_response = fake_online
ai_engine.get_active_voice_mode = lambda: "online"
engine._generate_ai_response("hello there", {}, "online")
check("online uses personality prompt", "MAYDAY" in (captured.get("system_prompt") or ""))
check("online history folded into text", "open youtube" in (captured.get("prompt") or ""))
check("online includes current command", "hello there" in (captured.get("prompt") or ""))
check("online sends no message list", captured.get("messages") is None)

engine._generate_ai_response = lambda command, params, mode: {
    "status": "success",
    "response": "Line one. Line two. Line three.",
    "source": "test",
}
result = engine.process_command("tell me a story")
check("spoken shortened", result["spoken"] == "Line one.", result["spoken"])
check("written stays detailed", result["response"] == "Line one. Line two. Line three.")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"  {PASS} passed, {FAIL} failed")
print("=" * 60)

sys.exit(1 if FAIL else 0)
