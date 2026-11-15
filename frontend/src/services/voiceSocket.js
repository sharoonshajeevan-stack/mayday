// ============================================================================
// REAL-TIME VOICE SOCKET - control/event channel for the Pipecat voice service
// File: src/services/voiceSocket.js
// Purpose: A tiny, dependency-free WebSocket client for MAYDAY's real-time
//          voice service.
//
// Audio never travels over this socket. The backend voice service drives the
// machine's own microphone and speakers (transport=local); this socket only
// carries JSON control messages in (start / stop / interrupt / text) and voice
// events out (state / transcript / response / interrupted / error).
//
// The URL can be overridden with VITE_MAYDAY_VOICE_WS, otherwise it defaults
// to the local service on 127.0.0.1:7860 (bound to localhost only).
//
// If the backend sets MAYDAY_VOICE_TOKEN, mirror it here with
// VITE_MAYDAY_VOICE_TOKEN. The token is optional and only protects against
// other local processes; the socket is never exposed beyond loopback.
// ============================================================================

const DEFAULT_VOICE_WS = "ws://127.0.0.1:7860/ws/voice";

const MAX_RECONNECT_DELAY_MS = 8000;

export function getVoiceSocketUrl({ host, port, token } = {}) {
  const base =
    import.meta?.env?.VITE_MAYDAY_VOICE_WS ||
    (host && port ? `ws://${host}:${port}/ws/voice` : DEFAULT_VOICE_WS);

  const resolvedToken = token || import.meta?.env?.VITE_MAYDAY_VOICE_TOKEN;

  if (!resolvedToken) {
    return base;
  }

  const separator = base.includes("?") ? "&" : "?";

  return `${base}${separator}token=${encodeURIComponent(resolvedToken)}`;
}

/**
 * VoiceSocket wraps a single control WebSocket with automatic reconnection.
 *
 *   const socket = new VoiceSocket({
 *     onEvent: (event) => { ... },   // parsed JSON events from the service
 *     onStatus: (status) => { ... }, // "connecting" | "open" | "closed" | "error"
 *   });
 *   socket.connect();
 *   socket.send("start");
 */
export class VoiceSocket {
  constructor({ url, host, port, token, onEvent, onStatus } = {}) {
    this.url = url || getVoiceSocketUrl({ host, port, token });
    this.onEvent = typeof onEvent === "function" ? onEvent : () => {};
    this.onStatus = typeof onStatus === "function" ? onStatus : () => {};

    this.socket = null;
    this.closedByUser = false;
    this.reconnectTimer = null;
    this.reconnectAttempts = 0;
  }

  connect() {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.closedByUser = false;
    this.onStatus("connecting");

    let socket;

    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      this.onStatus("error", error);
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStatus("open");
    };

    socket.onmessage = (message) => {
      let event;

      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }

      this.onEvent(event);
    };

    socket.onerror = (error) => {
      this.onStatus("error", error);
    };

    socket.onclose = () => {
      this.onStatus("closed");

      if (!this.closedByUser) {
        this.scheduleReconnect();
      }
    };
  }

  scheduleReconnect() {
    if (this.closedByUser || this.reconnectTimer) {
      return;
    }

    const delay = Math.min(
      500 * 2 ** this.reconnectAttempts,
      MAX_RECONNECT_DELAY_MS
    );

    this.reconnectAttempts += 1;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  isOpen() {
    return Boolean(this.socket && this.socket.readyState === WebSocket.OPEN);
  }

  send(type, payload = {}) {
    if (!this.isOpen()) {
      return false;
    }

    try {
      this.socket.send(JSON.stringify({ type, ...payload }));
      return true;
    } catch {
      return false;
    }
  }

  close() {
    this.closedByUser = true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // Ignore: the socket may already be gone.
      }

      this.socket = null;
    }
  }
}

export default VoiceSocket;
