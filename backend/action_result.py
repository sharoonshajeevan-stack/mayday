def _describe(result):
    """Build a human-readable message for a routed action result."""

    processes = result.get("processes")

    if isinstance(processes, list):
        return f"{len(processes)} process(es) running."

    if isinstance(processes, str) and processes.strip():
        return "Process list retrieved."

    system = result.get("system") or result.get("info")

    if isinstance(system, dict) and system:
        return "\n".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in system.items()
        )

    results = result.get("results")

    if isinstance(results, list):
        return f"Found {len(results)} result(s)."

    if result.get("path"):
        return f"Done: {result['path']}"

    if result.get("url"):
        return f"Opening {result['url']}"

    return "Command completed."


def format_action_result(result):
    if not result:
        return None

    status = result.get("status", "error")

    message = result.get("message") or result.get("response")

    if not message:
        message = _describe(result)

    return {
        "status": status,
        "response": message,
        "source": "system",
        "state": (
            "RESPONDING"
            if status in {"success", "confirmation_required"}
            else "IDLE"
        ),
    }
