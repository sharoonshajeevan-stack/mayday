# ============================================================================
# MAYDAY OS - REAL-TIME VOICE EVENT HUB
# File: backend/pipecat_voice/events.py
# Purpose: Fan out voice events (state, transcripts, responses, errors) to
#          every connected control client (the React HUD).
#
# Events can be emitted from the asyncio loop *or* from worker threads, so
# emit() is synchronous and always hops back onto the service loop.
# ============================================================================

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Voice states exposed to the UI.
STATE_IDLE = "IDLE"
STATE_LISTENING = "LISTENING"
STATE_THINKING = "THINKING"
STATE_SPEAKING = "SPEAKING"
STATE_EXECUTING = "EXECUTING"
STATE_ERROR = "ERROR"


class EventHub:
    """Broadcast voice events to connected WebSocket clients."""

    def __init__(self):
        self._clients = set()
        self._loop = None
        self._last_state = STATE_IDLE

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def bind_loop(self, loop):
        self._loop = loop

    def subscribe(self, websocket):
        self._clients.add(websocket)

    def unsubscribe(self, websocket):
        self._clients.discard(websocket)

    @property
    def client_count(self):
        return len(self._clients)

    @property
    def state(self):
        return self._last_state

    # ------------------------------------------------------------------
    # Emitting
    # ------------------------------------------------------------------
    def emit(self, event_type, **payload):
        """Queue an event for every connected client.

        Safe to call from any thread. If the loop is not available the event
        is dropped (nothing is listening yet).
        """
        if event_type == "state":
            self._last_state = payload.get("state", self._last_state)

        event = {"type": event_type, "timestamp": datetime.now().isoformat()}
        event.update(payload)

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        try:
            loop.call_soon_threadsafe(self._dispatch, event)
        except RuntimeError:
            # Loop is shutting down; drop the event.
            pass

    def _dispatch(self, event):
        for websocket in list(self._clients):
            try:
                asyncio.ensure_future(self._safe_send(websocket, event))
            except Exception:  # noqa: BLE001
                self._clients.discard(websocket)

    async def _safe_send(self, websocket, event):
        try:
            await websocket.send_json(event)
        except Exception:  # noqa: BLE001 - client went away
            self._clients.discard(websocket)
