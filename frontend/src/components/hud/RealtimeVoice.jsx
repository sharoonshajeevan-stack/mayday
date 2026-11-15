// src/components/hud/RealtimeVoice.jsx
//
// Real-time voice panel for MAYDAY.
//
// It controls the separate Pipecat voice service (continuous listening, VAD,
// turn detection, barge-in and streaming speech) that reuses MAYDAY's own
// Faster-Whisper, Kokoro and Gemini/Ollama engines.
//
// Privacy: nothing is activated automatically. The microphone only turns on
// when the user explicitly activates voice, and the panel always shows a
// visible mic indicator while the session is live.

import { useCallback, useEffect, useRef, useState } from "react";

import { useAIState } from "../../context/useAIState";
import {
  getRealtimeVoiceStatus,
  startRealtimeVoice,
  stopRealtimeVoice,
} from "../../services/api";
import { VoiceSocket } from "../../services/voiceSocket";

import "./RealtimeVoice.css";

// The real-time service has richer states than the rest of the HUD, so map
// them onto the four states the global HUD already understands.
const GLOBAL_STATE = {
  IDLE: "IDLE",
  LISTENING: "LISTENING",
  THINKING: "THINKING",
  SPEAKING: "RESPONDING",
  EXECUTING: "THINKING",
  INTERRUPTED: "LISTENING",
  ERROR: "IDLE",
};

const STATE_LABEL = {
  IDLE: "STANDBY",
  LISTENING: "LISTENING",
  THINKING: "THINKING",
  SPEAKING: "SPEAKING",
  EXECUTING: "EXECUTING",
  INTERRUPTED: "INTERRUPTED",
  ERROR: "ERROR",
};

const ACTION_LABEL = {
  open_app: "LAUNCHING APP",
  open_url: "OPENING SITE",
  shutdown: "SHUTTING DOWN",
  restart: "RESTARTING",
  get_processes: "READING PROCESSES",
  get_system_info: "READING SYSTEM",
  search_files: "SEARCHING FILES",
  system: "SYSTEM ACTION",
};

export default function RealtimeVoice() {
  const { setAIState } = useAIState();

  const [available, setAvailable] = useState(true);
  const [serviceUp, setServiceUp] = useState(false);
  const [connection, setConnection] = useState("offline");
  const [voiceState, setVoiceState] = useState("IDLE");
  const [transcript, setTranscript] = useState("");
  const [statusLine, setStatusLine] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const socketRef = useRef(null);
  const activeRef = useRef(false);
  const lastGlobalRef = useRef(null);
  const mountedRef = useRef(true);

  // ------------------------------------------------------------------
  // Global HUD integration
  // ------------------------------------------------------------------
  const publishState = useCallback(
    (next) => {
      const global = GLOBAL_STATE[next] || "IDLE";

      if (lastGlobalRef.current !== global) {
        lastGlobalRef.current = global;
        setAIState(global);

        window.dispatchEvent(
          new CustomEvent("mayday:state", { detail: global })
        );
      }
    },
    [setAIState]
  );

  const applyVoiceState = useCallback(
    (next) => {
      setVoiceState(next);
      publishState(next);
    },
    [publishState]
  );

  // ------------------------------------------------------------------
  // Service events
  // ------------------------------------------------------------------
  const handleEvent = useCallback(
    (event) => {
      if (!mountedRef.current || !event || !event.type) {
        return;
      }

      switch (event.type) {
        case "hello":
        case "status":
          if (typeof event.running === "boolean") {
            setServiceUp(event.running);
            activeRef.current = event.running;
          }
          if (event.state && !event.running) {
            applyVoiceState("IDLE");
          }
          break;

        case "listening":
          activeRef.current = Boolean(event.value);
          setServiceUp(Boolean(event.value));
          break;

        case "state":
          setError("");
          applyVoiceState(event.state || "IDLE");
          break;

        case "transcript":
          setTranscript(event.text || "");
          break;

        case "executing":
          setStatusLine(
            `${ACTION_LABEL[event.action_kind] || "EXECUTING"}${
              event.command ? ` · ${event.command}` : ""
            }`
          );
          applyVoiceState("EXECUTING");
          break;

        case "response":
          setStatusLine("");
          if (event.text) {
            window.dispatchEvent(
              new CustomEvent("mayday:response", { detail: event.text })
            );
          }
          break;

        case "interrupted":
          setStatusLine("");
          setTranscript("");
          applyVoiceState("INTERRUPTED");
          break;

        case "error":
          setError(event.message || "Voice error");
          applyVoiceState("ERROR");
          break;

        default:
          break;
      }
    },
    [applyVoiceState]
  );

  const handleConnectionStatus = useCallback((status) => {
    setConnection(status);
  }, []);

  // ------------------------------------------------------------------
  // Socket lifecycle
  // ------------------------------------------------------------------
  const openSocket = useCallback(
    ({ host, port, token } = {}) => {
      if (socketRef.current) {
        return socketRef.current;
      }

      const socket = new VoiceSocket({
        host,
        port,
        token,
        onEvent: handleEvent,
        onStatus: handleConnectionStatus,
      });

      socketRef.current = socket;
      socket.connect();

      return socket;
    },
    [handleEvent, handleConnectionStatus]
  );

  const closeSocket = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
  }, []);

  // ------------------------------------------------------------------
  // Status on mount (never auto-activates the microphone)
  // ------------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true;

    let cancelled = false;

    (async () => {
      const result = await getRealtimeVoiceStatus();

      if (cancelled || !mountedRef.current) {
        return;
      }

      if (!result.success) {
        setAvailable(false);
        setConnection("offline");
        return;
      }

      const data = result.data || {};

      setAvailable(data.available !== false);

      if (data.available !== false && data.running) {
        setServiceUp(true);
        openSocket({
          host: data.host,
          port: data.port,
          token: data.token,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [openSocket]);

  // ------------------------------------------------------------------
  // Cleanup on unmount: release the mic and restore legacy voice
  // ------------------------------------------------------------------
  useEffect(() => {
    return () => {
      mountedRef.current = false;

      const socket = socketRef.current;

      if (socket) {
        socket.send("stop");
        socket.close();
        socketRef.current = null;
      }

      if (activeRef.current) {
        window.dispatchEvent(new CustomEvent("mayday:voice-enable"));
      }
    };
  }, []);

  // ------------------------------------------------------------------
  // Controls
  // ------------------------------------------------------------------
  const activate = useCallback(async () => {
    if (busy || !available) {
      return;
    }

    setBusy(true);
    setError("");
    setStatusLine("");
    setTranscript("");
    setConnection("connecting");

    // The real-time pipeline replaces the legacy mic/TTS while it is live.
    window.dispatchEvent(new CustomEvent("mayday:voice-disable"));

    const started = await startRealtimeVoice();

    if (!mountedRef.current) {
      setBusy(false);
      return;
    }

    if (!started.success) {
      setError(started.error || "Could not start the voice service.");
      setConnection("offline");
      applyVoiceState("ERROR");
      window.dispatchEvent(new CustomEvent("mayday:voice-enable"));
      setBusy(false);
      return;
    }

    const data = started.data || {};
    const socket = openSocket({
      host: data.host,
      port: data.port,
      token: data.token,
    });

    // Start listening as soon as the socket is ready.
    let attempts = 0;
    const startSession = () => {
      attempts += 1;

      if (socket.isOpen()) {
        socket.send("start");
        activeRef.current = true;
        setServiceUp(true);
        applyVoiceState("LISTENING");
        setBusy(false);
        return;
      }

      if (attempts > 60 || !mountedRef.current) {
        setError("Could not reach the voice service.");
        applyVoiceState("ERROR");
        setBusy(false);
        return;
      }

      setTimeout(startSession, 250);
    };

    startSession();
  }, [available, busy, openSocket, applyVoiceState]);

  const deactivate = useCallback(async () => {
    if (busy) {
      return;
    }

    setBusy(true);

    const socket = socketRef.current;

    if (socket) {
      socket.send("stop");
    }

    closeSocket();

    await stopRealtimeVoice();

    if (!mountedRef.current) {
      setBusy(false);
      return;
    }

    activeRef.current = false;
    setServiceUp(false);
    setTranscript("");
    setStatusLine("");
    setError("");
    setConnection("offline");
    applyVoiceState("IDLE");
    window.dispatchEvent(new CustomEvent("mayday:voice-enable"));
    setBusy(false);
  }, [busy, closeSocket, applyVoiceState]);

  const interrupt = useCallback(() => {
    const socket = socketRef.current;

    if (socket && socket.isOpen()) {
      socket.send("interrupt");
      applyVoiceState("LISTENING");
    }
  }, [applyVoiceState]);

  const reconnect = useCallback(() => {
    setError("");
    closeSocket();

    const socket = openSocket();
    socket.connect();
  }, [closeSocket, openSocket]);

  // ------------------------------------------------------------------
  // Derived display
  // ------------------------------------------------------------------
  const active = serviceUp && connection !== "offline";

  const className = [
    "realtime-voice",
    `state-${voiceState.toLowerCase()}`,
    active ? "active" : "inactive",
    `conn-${connection}`,
  ].join(" ");

  const canInterrupt = ["THINKING", "SPEAKING", "EXECUTING"].includes(
    voiceState
  );

  return (
    <div className={className}>
      <div className="realtime-voice-header">
        <span className="realtime-voice-title">VOICE LINK</span>

        <span className={`realtime-voice-conn ${connection}`}>
          {connection === "open"
            ? "LINKED"
            : connection === "connecting"
              ? "LINKING"
              : "OFFLINE"}
        </span>
      </div>

      <div className="realtime-voice-state-row">
        <span className={`realtime-voice-dot ${voiceState.toLowerCase()}`} />

        <span className="realtime-voice-state">
          {STATE_LABEL[voiceState] || "IDLE"}
        </span>

        {active && <span className="realtime-voice-mic" title="Microphone live">● MIC</span>}
      </div>

      <div className="realtime-voice-transcript">
        {statusLine || transcript || (
          <span className="realtime-voice-muted">
            {available
              ? active
                ? "Listening for your voice…"
                : "Voice idle"
              : "Real-time voice unavailable"}
          </span>
        )}
      </div>

      {error && <div className="realtime-voice-error">{error}</div>}

      <div className="realtime-voice-actions">
        <button
          type="button"
          className={`realtime-voice-button ${active ? "stop" : "start"}`}
          onClick={active ? deactivate : activate}
          disabled={busy || !available}
        >
          {busy ? "…" : active ? "DEACTIVATE" : "ACTIVATE VOICE"}
        </button>

        {canInterrupt && (
          <button
            type="button"
            className="realtime-voice-button interrupt"
            onClick={interrupt}
          >
            STOP
          </button>
        )}

        {connection === "closed" && available && (
          <button
            type="button"
            className="realtime-voice-button reconnect"
            onClick={reconnect}
          >
            RECONNECT
          </button>
        )}
      </div>
    </div>
  );
}
