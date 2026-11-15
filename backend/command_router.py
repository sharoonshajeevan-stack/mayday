import re


from system_commands import (
    execute_launch_app,
    execute_open_url,
    execute_get_processes,
    execute_get_system_info,
    execute_shutdown,
    execute_restart,
    execute_lock,
    execute_sleep,
    confirm_shutdown,
    confirm_restart,
    cancel_power_action,
    execute_screenshot,
)

from file_search import search_files, open_file

from window_commands import (
    minimize_window,
    maximize_window,
    restore_window,
    request_close_window,
    confirm_close_window,
)

from file_commands import open_folder



APP_ALIASES = {
    "notepad": "notepad",
    "notepad.exe": "notepad",

    "calculator": "calculator",
    "calc": "calculator",
    "calculator app": "calculator",

    "chrome": "chrome",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "google browser": "chrome",

    "explorer": "explorer",
    "file explorer": "explorer",
    "windows explorer": "explorer",

    "cmd": "cmd",
    "command prompt": "cmd",

    "paint": "paint",
    "ms paint": "paint",
    "mspaint": "paint",

    "task manager": "task manager",
    "taskmgr": "task manager",

    "snipping tool": "snipping tool",
    "snippingtool": "snipping tool",

    "wordpad": "wordpad",

    "control panel": "control panel",
    "control": "control panel",

    "powershell": "powershell",
    "power shell": "powershell",

    "terminal": "terminal",
    "windows terminal": "terminal",

    "edge": "edge",
    "microsoft edge": "edge",

    "vs code": "vs code",
    "vscode": "vs code",
    "visual studio code": "vs code",

    "settings": "settings",
    "windows settings": "settings",
}


FOLDER_NAMES = {
    "desktop",
    "document",
    "documents",
    "download",
    "downloads",
    "picture",
    "pictures",
    "video",
    "videos",
    "music",
}


FOLDER_ALIASES = {
    "open desktop": "desktop",

    "open document": "documents",
    "open documents": "documents",

    "open download": "downloads",
    "open downloads": "downloads",

    "open picture": "pictures",
    "open pictures": "pictures",

    "open video": "videos",
    "open videos": "videos",

    "open music": "music",

        "show desktop": "desktop",
    "show my desktop": "desktop",

    "show documents": "documents",
    "show my documents": "documents",

    "show downloads": "downloads",
    "show my downloads": "downloads",

    "show pictures": "pictures",
    "show my pictures": "pictures",

    "show videos": "videos",
    "show my videos": "videos",

    "show music": "music",
    "show my music": "music",
}

# Words people add around a command that should not change what it means.
LEADING_FILLERS = (
    "please ",
    "kindly ",
    "hey mayday ",
    "hey ",
    "mayday ",
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "can u ",
    "could u ",
    "would u ",
    "i want you to ",
    "i need you to ",
    "i would like you to ",
    "i'd like you to ",
    "do you mind ",
    "just ",
    "go ahead and ",
    "go and ",
)

TRAILING_FILLERS = (
    " for me please",
    " for us please",
    " for me",
    " for us",
    " please",
    " right now",
    " now",
    " asap",
    " immediately",
    " thank you mayday",
    " thank you",
    " thanks",
    " buddy",
    " mate",
    " if you can",
    " if possible",
)


def _strip_fillers(text):
    """Remove polite/filler words from either end of a command.

    This is what makes "open notepad for me" behave like "open notepad".
    """
    changed = True

    while changed:
        changed = False

        for filler in LEADING_FILLERS:
            if text.startswith(filler):
                text = text[len(filler):].strip()
                changed = True

        for filler in TRAILING_FILLERS:
            if text.endswith(filler):
                text = text[: -len(filler)].strip()
                changed = True

    return text.strip()


def normalize_command(text):
    text = text.strip().lower()

    # Remove common punctuation from voice transcription.
    text = re.sub(r"[.,!?;:]+$", "", text).strip()

    return _strip_fillers(text)


def route_command(command):
    text = normalize_command(str(command or ""))

    if not text:
        return None

    # ------------------------------------------------------------
    # OPEN URL
    # ------------------------------------------------------------

    url_match = re.match(
        r"^(open|go to|visit)\s+(.+)$",
        text,
    )

    if url_match:
        target = url_match.group(2).strip()

        url_aliases = {
            "youtube": "https://youtube.com",
            "youtube.com": "https://youtube.com",
            "google": "https://google.com",
            "google.com": "https://google.com",
            "github": "https://github.com",
            "github.com": "https://github.com",
        }

        if target in url_aliases:
            return execute_open_url(url_aliases[target])

        if target.startswith(("http://", "https://", "www.")):
            return execute_open_url(target)

    # ------------------------------------------------------------
    # OPEN APPLICATION
    # ------------------------------------------------------------

    app_patterns = [
        r"^open\s+(.+)$",
        r"^launch\s+(.+)$",
        r"^start\s+(.+)$",
        r"^run\s+(.+)$",
    ]

    for pattern in app_patterns:
        match = re.match(pattern, text)

        if not match:
            continue

        app_name = match.group(1).strip()

        # "open the notepad app" -> "notepad"
        app_name = re.sub(r"^(the|my|up)\s+", "", app_name)
        app_name = re.sub(
            r"\s+(app|application|program|window|folder)$",
            "",
            app_name,
        )
        app_name = app_name.strip()

        if app_name in APP_ALIASES:
            return execute_launch_app(
                APP_ALIASES[app_name]
            )

        # "open my downloads" -> open the Downloads folder.
        if app_name in FOLDER_NAMES:
            return open_folder(app_name)

        # Unknown but app-like name: try an executable on the PATH.
        # If nothing matches, fall through so the AI can answer instead.
        if re.fullmatch(r"[a-z0-9][a-z0-9 .+#_-]{0,39}", app_name):
            result = execute_launch_app(app_name)

            if result.get("status") == "success":
                return result

    # ------------------------------------------------------------
    # SCREENSHOT
    # ------------------------------------------------------------

    if text in {
        "take screenshot",
        "take a screenshot",
        "screenshot",
        "capture screen",
        "capture the screen",
        "capture screenshot",
        "capture a screenshot",
        "take screen shot",
        "take a screen shot",
    }:
        return execute_screenshot()

    # ------------------------------------------------------------
    # PROCESS LIST
    # ------------------------------------------------------------

    process_commands = {
        "show processes",
        "list processes",
        "get processes",
        "show running processes",
        "what processes are running",
    }

    if text in process_commands:
        return execute_get_processes()

    # ------------------------------------------------------------
    # SYSTEM INFORMATION
    # ------------------------------------------------------------

    system_commands = {
        "system information",
        "system info",
        "get system information",
        "show system information",
        "show system info",
    }

    if text in system_commands:
        return execute_get_system_info()

    # ------------------------------------------------------------
    # POWER CONTROLS
    # ------------------------------------------------------------

    if text in {
        "shutdown",
        "shut down",
        "shutdown computer",
        "shut down computer",
    }:
        return execute_shutdown()

    if text in {
        "restart",
        "restart computer",
        "reboot",
        "reboot computer",
    }:
        return execute_restart()

    if text in {
        "lock",
        "lock computer",
        "lock pc",
    }:
        return execute_lock()

    if text in {
        "sleep",
        "sleep computer",
        "sleep pc",
    }:
        return execute_sleep()

    # ------------------------------------------------------------
    # POWER CONFIRMATION
    # ------------------------------------------------------------

    if text in {
        "yes shutdown",
        "confirm shutdown",
        "shutdown confirmed",
    }:
        return confirm_shutdown()

    if text in {
        "yes restart",
        "confirm restart",
        "restart confirmed",
    }:
        return confirm_restart()

    if text in {
        "cancel shutdown",
        "cancel restart",
        "cancel power action",
        "no",
        "cancel",
    }:
        return cancel_power_action()

    # ------------------------------------------------------------
    # FOLDER COMMANDS
    # ------------------------------------------------------------

    if text in {
        "open desktop",
        "open document",
        "open documents",
        "open download",
        "open downloads",
        "open picture",
        "open pictures",
        "open video",
        "open videos",
        "open music",
    }:
        folder = text[5:].strip()
        return open_folder(folder)

    return None