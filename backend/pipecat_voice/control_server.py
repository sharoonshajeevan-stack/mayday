# ============================================================================
# MAYDAY OS - REAL-TIME VOICE CONTROL SERVER
# File: backend/pipecat_voice/control_server.py
# Purpose: Small aiohttp server that exposes the real-time voice session to
#          the MAYDAY HUD:
#
#   GET  /voice/health   - liveness + status (JSON)
#   GET  /voice/status   - status (JSON)
#   GET  /ws/voice       - control + event WebSocket
#
# The WebSocket carries JSON control messages *into* the service and voice
# events *out* of it. Audio itself never travels over this socket - the
# service drives the machine's own microphone and speakers (transport=local).
# ============================================================================

import json
import logging

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


class ControlServer:
    """Expose the voice agent over HTTP + WebSocket."""

    def __init__(self, *, agent, hub, config, on_shutdown=None):
        self._agent = agent
        self._hub = hub
        self._config = config
        self._on_shutdown = on_shutdown

    # ------------------------------------------------------------------
    def build_app(self):
        app = web.Application()
        app.router.add_get("/voice/health", self._health)
        app.router.add_get("/voice/status", self._status)
        app.router.add_post("/voice/shutdown", self._shutdown)
        app.router.add_get("/ws/voice", self._websocket)
        return app

    # ------------------------------------------------------------------
    def _authorized(self, request):
        token = self._config.token
        if not token:
            return True
        supplied = request.query.get("token") or request.headers.get("X-Mayday-Token")
        return supplied == token

    async def _health(self, request):
        return web.json_response({"status": "ok", **self._agent.status()})

    async def _status(self, request):
        return web.json_response({"status": "ok", **self._agent.status()})

    async def _shutdown(self, request):
        """Ask the service to stop cleanly (used by the Flask launcher)."""
        if not self._authorized(request):
            return web.Response(status=401, text="unauthorized")

        logger.info("Shutdown requested over HTTP")

        if self._on_shutdown is not None:
            self._on_shutdown()

        return web.json_response({"status": "ok", "message": "shutting down"})

    # ------------------------------------------------------------------
    async def _websocket(self, request):
        if not self._authorized(request):
            return web.Response(status=401, text="unauthorized")

        websocket = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
        await websocket.prepare(request)

        self._hub.subscribe(websocket)
        logger.info("Voice control client connected (%d total)", self._hub.client_count)

        try:
            await websocket.send_json({"type": "hello", **self._agent.status()})

            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    await self._handle(websocket, message.data)
                elif message.type == WSMsgType.ERROR:
                    break
        except Exception:  # noqa: BLE001 - client disconnects are normal
            logger.debug("Voice control socket error", exc_info=True)
        finally:
            self._hub.unsubscribe(websocket)
            logger.info(
                "Voice control client disconnected (%d left)", self._hub.client_count
            )

        return websocket

    # ------------------------------------------------------------------
    async def _handle(self, websocket, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            await websocket.send_json({"type": "error", "message": "invalid JSON"})
            return

        if not isinstance(data, dict):
            await websocket.send_json({"type": "error", "message": "invalid message"})
            return

        kind = str(data.get("type") or "").strip().lower()

        try:
            if kind == "start":
                await self._agent.start()
                await websocket.send_json({"type": "status", **self._agent.status()})
            elif kind == "stop":
                await self._agent.stop()
                await websocket.send_json({"type": "status", **self._agent.status()})
            elif kind == "interrupt":
                await self._agent.interrupt()
            elif kind == "text":
                ok = await self._agent.send_text(data.get("text"))
                if not ok:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "MAYDAY is not listening yet - start it first.",
                        }
                    )
            elif kind == "speak":
                await self._agent.speak(data.get("text"))
            elif kind == "status":
                await websocket.send_json({"type": "status", **self._agent.status()})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json(
                    {"type": "error", "message": f"unknown command '{kind}'"}
                )
        except Exception as exc:  # noqa: BLE001 - never drop the socket
            logger.exception("Voice control command failed: %s", kind)
            await websocket.send_json({"type": "error", "message": str(exc)})
