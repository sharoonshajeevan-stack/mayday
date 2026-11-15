// src/components/SpeechToText.jsx
//
// Microphone input for MAYDAY. Records via the Python backend
// (Faster-Whisper) and forwards the transcript as a command.
//
// Flow: press the mic -> backend records -> backend auto-stops on silence
//       -> transcript is fetched -> "mayday:command" is dispatched.

import { useEffect, useRef, useState } from "react";

import { useAIState } from "../context/useAIState";
import {
  startRecording,
  stopRecording,
  getSTTStatus,
  clearTranscript,
} from "../services/api";

export default function SpeechToText() {
  const { setAIState } = useAIState();

  const [status, setStatus] = useState("idle"); // idle | listening | processing
  const [hint, setHint] = useState("");

  const statusRef = useRef("idle");
  const enabledRef = useRef(true);
  const pollRef = useRef(null);
  const toggleRef = useRef(() => {});

  useEffect(() => {
    const applyStatus = (next) => {
      statusRef.current = next;
      setStatus(next);
    };

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const finishRecording = async () => {
      stopPolling();
      applyStatus("processing");
      setAIState("THINKING");

      try {
        const result = await stopRecording();
        const transcript = String(result?.data?.data?.transcript || "").trim();

        if (transcript) {
          setHint(transcript);

          window.dispatchEvent(
            new CustomEvent("mayday:command", { detail: transcript }),
          );
        } else {
          setHint("I didn't catch that.");
          setAIState("IDLE");
        }
      } catch (error) {
        console.warn("MAYDAY transcription failed:", error);
        setHint("Voice input failed.");
        setAIState("IDLE");
      } finally {
        applyStatus("idle");

        window.setTimeout(() => setHint(""), 2600);
      }
    };

    const beginListening = async () => {
      if (!enabledRef.current || statusRef.current !== "idle") {
        return;
      }

      setHint("");

      try {
        await clearTranscript();

        const started = await startRecording();

        if (!started?.success) {
          setHint("Microphone unavailable.");
          setAIState("IDLE");
          return;
        }

        applyStatus("listening");
        setAIState("LISTENING");
        stopPolling();

        // The backend stops automatically on silence; wait for that and
        // then fetch the transcript.
        pollRef.current = setInterval(async () => {
          const result = await getSTTStatus();
          const recording = Boolean(result?.data?.stt?.is_recording);

          if (!recording && statusRef.current === "listening") {
            finishRecording();
          }
        }, 500);
      } catch (error) {
        console.warn("MAYDAY could not start recording:", error);
        applyStatus("idle");
        setHint("Microphone unavailable.");
        setAIState("IDLE");
      }
    };

    const handleToggle = () => {
      if (statusRef.current === "listening") {
        finishRecording();
        return;
      }

      if (statusRef.current === "idle") {
        beginListening();
      }
    };

    toggleRef.current = handleToggle;

    const handleVoiceStart = () => beginListening();

    const handleDisable = () => {
      enabledRef.current = false;

      if (statusRef.current === "listening") {
        finishRecording();
      }
    };

    const handleEnable = () => {
      enabledRef.current = true;
    };

    window.addEventListener("mayday:voice-start", handleVoiceStart);
    window.addEventListener("mayday:voice-disable", handleDisable);
    window.addEventListener("mayday:voice-enable", handleEnable);

    return () => {
      window.removeEventListener("mayday:voice-start", handleVoiceStart);
      window.removeEventListener("mayday:voice-disable", handleDisable);
      window.removeEventListener("mayday:voice-enable", handleEnable);

      stopPolling();
    };
  }, [setAIState]);

  const listening = status === "listening";
  const processing = status === "processing";

  const accent = listening
    ? "rgba(255, 153, 0, 0.95)"
    : processing
      ? "rgba(255, 215, 0, 0.9)"
      : "rgba(0, 191, 255, 0.8)";

  return (
    <div
      style={{
        position: "fixed",
        bottom: "18px",
        right: "20px",
        zIndex: 99999,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: "6px",
        fontFamily: "monospace",
      }}
    >
      {hint ? (
        <div
          style={{
            maxWidth: "260px",
            padding: "4px 8px",
            fontSize: "9px",
            letterSpacing: "1px",
            color: "rgba(220, 240, 255, 0.85)",
            background: "rgba(0, 20, 40, 0.55)",
            border: `1px solid ${accent}`,
            borderRadius: "4px",
          }}
        >
          {hint}
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => toggleRef.current()}
        title={
          listening
            ? "Stop listening"
            : processing
              ? "Transcribing..."
              : "Speak to MAYDAY"
        }
        aria-label="Toggle voice input"
        style={{
          width: "46px",
          height: "46px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: "50%",
          cursor: processing ? "wait" : "pointer",
          color: accent,
          background: listening
            ? "rgba(255, 153, 0, 0.16)"
            : "rgba(0, 25, 45, 0.55)",
          border: `1px solid ${accent}`,
          boxShadow: listening ? `0 0 14px ${accent}` : "none",
          transition: "all 160ms ease",
        }}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <line x1="12" y1="18" x2="12" y2="22" />
        </svg>
      </button>

      <span
        style={{
          fontSize: "8px",
          letterSpacing: "2px",
          color: accent,
          opacity: 0.75,
        }}
      >
        {listening ? "LISTENING" : processing ? "TRANSCRIBING" : "VOICE INPUT"}
      </span>
    </div>
  );
}
