// src/components/TextToSpeech.jsx
//
// Speaks MAYDAY's replies using the backend Kokoro voice engine.
// The browser's built-in speechSynthesis is no longer used.
//
// "mayday:speak" carries the short version MAYDAY says out loud, while
// "mayday:response" carries the full text shown on screen. We prefer the
// spoken version and fall back to the full text if it is not provided.

import { useEffect, useRef, useState } from "react";

import { speakText, stopSpeaking, getTTSStatus } from "../services/api";

export default function TextToSpeech() {
  const [speaking, setSpeaking] = useState(false);

  const lastSpoken = useRef("");
  const mutedRef = useRef(false);
  const pollRef = useRef(null);
  const pendingRef = useRef(null);

  useEffect(() => {
    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const cancelPending = () => {
      if (pendingRef.current) {
        clearTimeout(pendingRef.current);
        pendingRef.current = null;
      }
    };

    // The backend synthesizes in the background, so poll its status until
    // playback finishes and then clear the "speaking" indicator.
    const watchPlayback = () => {
      stopPolling();

      let idleReads = 0;

      pollRef.current = setInterval(async () => {
        const result = await getTTSStatus();
        const isSpeaking = Boolean(result?.data?.tts?.is_speaking);

        if (isSpeaking) {
          idleReads = 0;
          return;
        }

        idleReads += 1;

        if (idleReads >= 2) {
          stopPolling();
          setSpeaking(false);
        }
      }, 400);
    };

    const speak = async (text) => {
      const clean = String(text || "").trim();

      if (!clean || clean === lastSpoken.current || mutedRef.current) {
        return;
      }

      lastSpoken.current = clean;

      setSpeaking(true);

      const result = await speakText(clean);

      if (!result?.success) {
        console.warn("MAYDAY backend TTS is unavailable.");
        setSpeaking(false);
        return;
      }

      watchPlayback();
    };

    // The short spoken version (preferred).
    const handleSpeak = (event) => {
      cancelPending();
      speak(event.detail);
    };

    // Fallback: if only the full response arrives, speak it.
    const handleResponse = (event) => {
      cancelPending();
      const text = String(event.detail || "");
      pendingRef.current = setTimeout(() => speak(text), 0);
    };

    const handleDisable = () => {
      mutedRef.current = true;
      cancelPending();
      stopPolling();
      stopSpeaking();
      setSpeaking(false);
    };

    const handleEnable = () => {
      mutedRef.current = false;
    };

    window.addEventListener("mayday:speak", handleSpeak);
    window.addEventListener("mayday:response", handleResponse);
    window.addEventListener("mayday:voice-disable", handleDisable);
    window.addEventListener("mayday:voice-enable", handleEnable);

    return () => {
      window.removeEventListener("mayday:speak", handleSpeak);
      window.removeEventListener("mayday:response", handleResponse);
      window.removeEventListener("mayday:voice-disable", handleDisable);
      window.removeEventListener("mayday:voice-enable", handleEnable);

      cancelPending();
      stopPolling();
      stopSpeaking();
    };
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        bottom: "20px",
        left: "20px",
        zIndex: 99999,
        fontFamily: "monospace",
        fontSize: "8px",
        letterSpacing: "2px",
        color: speaking
          ? "rgba(255, 153, 0, 0.7)"
          : "rgba(0, 191, 255, 0.45)",
        pointerEvents: "none",
      }}
    >
      {speaking ? "MAYDAY SPEAKING" : "VOICE READY"}
    </div>
  );
}
