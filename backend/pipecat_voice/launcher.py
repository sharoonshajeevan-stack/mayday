# ============================================================================
# MAYDAY OS - REAL-TIME VOICE SERVICE LAUNCHER
# File: backend/pipecat_voice/launcher.py
# Purpose: Clean lifecycle management for the separate Pipecat voice service
#          process. The Flask backend uses this to start / stop / inspect the
#          service so the user never has to manage two terminals.
#
# Nothing here is Windows-startup automation (that is intentionally deferred
# until the integration is proven reliable) - it is plain process management
# driven by an explicit API call or the app's own shutdown.
# ============================================================================

import atexit
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

# pipecat_voice/ -> backend/
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7860

# Give the service time to import Pipecat and bind the socket.
START_TIMEOUT_SECS = 60.0

_process = None
_lock = threading.Lock()


def _health_url(host, port):
    return f"http://{host}:{port}/voice/health"


def is_service_up(host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=0.6):
    """Return True when the voice service answers its health check."""
    try:
        with urllib.request.urlopen(_health_url(host, port), timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:  # noqa: BLE001 - any failure means "not up"
        return False


def _env_for(host, port, token):
    env = dict(os.environ)
    env["MAYDAY_VOICE_HOST"] = host
    env["MAYDAY_VOICE_PORT"] = str(port)
    if token:
        env["MAYDAY_VOICE_TOKEN"] = token
    return env


def start_service(
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
    token=None,
    wait_secs=START_TIMEOUT_SECS,
):
    """Start the voice service if it is not already running."""
    global _process

    with _lock:
        if is_service_up(host, port):
            return {
                "status": "success",
                "message": "already running",
                "pid": _process.pid if _process and _process.poll() is None else None,
            }

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        logger.info("Starting MAYDAY real-time voice service (%s:%s)", host, port)

        try:
            _process = subprocess.Popen(
                [sys.executable, "-m", "pipecat_voice.service"],
                cwd=BACKEND_DIR,
                env=_env_for(host, port, token),
                creationflags=creationflags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not launch the voice service")
            _process = None
            return {"status": "error", "message": str(exc)}

        deadline = time.time() + max(1.0, float(wait_secs))

        while time.time() < deadline:
            if is_service_up(host, port):
                return {
                    "status": "success",
                    "message": "started",
                    "pid": _process.pid,
                }

            if _process.poll() is not None:
                code = _process.returncode
                _process = None
                return {
                    "status": "error",
                    "message": f"voice service exited early (code {code})",
                }

            time.sleep(0.5)

        return {
            "status": "error",
            "message": "voice service did not become healthy in time",
            "pid": _process.pid if _process else None,
        }


def _request_shutdown(host, port, timeout=5.0):
    """Ask a running service to stop cleanly. Returns True on success."""
    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/voice/shutdown", method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:  # noqa: BLE001 - the service may already be gone
        return False


def stop_service(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Stop the voice service started by this process (if any)."""
    global _process

    with _lock:
        # Ask for a clean shutdown first so the pipeline releases the
        # microphone and speakers gracefully. This also covers a service that
        # was started outside this process.
        if is_service_up(host, port):
            _request_shutdown(host, port)

        if _process is None:
            return {"status": "success", "message": "shutdown requested"}

        if _process.poll() is not None:
            _process = None
            return {"status": "success", "message": "not running"}

        logger.info("Stopping MAYDAY real-time voice service (pid=%s)", _process.pid)

        try:
            try:
                _process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                logger.warning("Voice service did not stop; terminating it")
                _process.terminate()

                try:
                    _process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Voice service still alive; killing it")
                    _process.kill()
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping the voice service")
        finally:
            _process = None

        return {"status": "success", "message": "stopped"}


def service_status(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Return whether the voice service is reachable and managed here."""
    token = (os.getenv("MAYDAY_VOICE_TOKEN", "") or "").strip()

    return {
        "running": is_service_up(host, port),
        "managed": _process is not None and _process.poll() is None,
        "pid": _process.pid if _process and _process.poll() is None else None,
        "url": _health_url(host, port),
        "token_required": bool(token),
    }


def _cleanup():
    try:
        stop_service()
    except Exception:  # noqa: BLE001
        pass


atexit.register(_cleanup)
