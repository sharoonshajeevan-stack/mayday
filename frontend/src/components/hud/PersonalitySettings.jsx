// src/components/hud/PersonalitySettings.jsx
//
// Compact settings panel for MAYDAY's personality layer. Values are persisted
// by the backend (backend/personality.json), so they survive a restart and are
// shared by both the online and offline engines.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getPersonalitySettings,
  updatePersonalitySettings,
  getTTSVoices,
} from "../../services/api";

import "./PersonalitySettings.css";

const COMMENTARY_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "minimal", label: "Minimal" },
  { value: "balanced", label: "Balanced" },
  { value: "chatty", label: "Chatty" },
];

const LENGTH_OPTIONS = [
  { value: "short", label: "Short" },
  { value: "medium", label: "Medium" },
  { value: "detailed", label: "Detailed" },
];

export default function PersonalitySettings() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [voices, setVoices] = useState([]);
  const [status, setStatus] = useState("");

  // Slider drags fire many changes; batch them into one save.
  const pendingRef = useRef({});
  const timerRef = useRef(null);

  const commit = useCallback(() => {
    const patch = pendingRef.current;
    pendingRef.current = {};

    if (!Object.keys(patch).length) {
      return;
    }

    updatePersonalitySettings(patch).then((result) => {
      if (result?.success && result.data?.settings) {
        setSettings(result.data.settings);
        setStatus("Saved");
      } else {
        setStatus("Save failed");
      }
    });
  }, []);

  const apply = useCallback(
    (patch) => {
      setSettings((prev) => ({ ...(prev || {}), ...patch }));
      pendingRef.current = { ...pendingRef.current, ...patch };

      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      timerRef.current = setTimeout(commit, 400);
    },
    [commit],
  );

  useEffect(() => {
    getPersonalitySettings().then((result) => {
      if (result?.success) {
        setSettings(result.data?.settings || {});
      }
    });

    getTTSVoices().then((result) => {
      if (result?.success) {
        setVoices(result.data?.voices || []);
      }
    });

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const reset = async () => {
    const result = await updatePersonalitySettings({ reset: true });

    if (result?.success) {
      setSettings(result.data?.settings || {});
      setStatus("Defaults restored");
    }
  };

  const value = settings || {};

  return (
    <div className="personality-settings">
      <button
        type="button"
        className={`personality-toggle ${open ? "open" : ""}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Toggle personality settings"
        aria-expanded={open}
      >
        <span className="personality-toggle-icon" aria-hidden="true">
          &#9881;
        </span>

        <span className="personality-toggle-label">PERSONALITY</span>
      </button>

      {open && (
        <div className="personality-panel" role="dialog" aria-label="Personality settings">
          <div className="personality-panel-header">
            <span>PERSONALITY</span>

            <button
              type="button"
              className="personality-close"
              onClick={() => setOpen(false)}
              aria-label="Close personality settings"
            >
              &times;
            </button>
          </div>

          <div className="personality-row">
            <label className="personality-switch">
              <input
                type="checkbox"
                checked={Boolean(value.personality_enabled)}
                onChange={(event) =>
                  apply({ personality_enabled: event.target.checked })
                }
              />
              <span>Personality enabled</span>
            </label>
          </div>

          <div className="personality-row">
            <label className="personality-switch">
              <input
                type="checkbox"
                checked={Boolean(value.quiet_mode)}
                onChange={(event) =>
                  apply({ quiet_mode: event.target.checked })
                }
              />
              <span>Quiet mode</span>
            </label>
          </div>

          <div className="personality-row">
            <label className="personality-switch">
              <input
                type="checkbox"
                checked={Boolean(value.sarcasm_enabled)}
                onChange={(event) =>
                  apply({ sarcasm_enabled: event.target.checked })
                }
              />
              <span>Sarcasm</span>
            </label>

            <span className="personality-value">
              {value.sarcasm_level ?? 0}%
            </span>
          </div>

          <input
            className="personality-slider"
            type="range"
            min="0"
            max="100"
            step="5"
            value={value.sarcasm_level ?? 0}
            disabled={!value.sarcasm_enabled}
            onChange={(event) =>
              apply({ sarcasm_level: Number(event.target.value) })
            }
            aria-label="Sarcasm level"
          />

          <div className="personality-row">
            <label className="personality-switch">
              <input
                type="checkbox"
                checked={Boolean(value.humour_enabled)}
                onChange={(event) =>
                  apply({ humour_enabled: event.target.checked })
                }
              />
              <span>Humour</span>
            </label>

            <span className="personality-value">
              {value.humour_level ?? 0}%
            </span>
          </div>

          <input
            className="personality-slider"
            type="range"
            min="0"
            max="100"
            step="5"
            value={value.humour_level ?? 0}
            disabled={!value.humour_enabled}
            onChange={(event) =>
              apply({ humour_level: Number(event.target.value) })
            }
            aria-label="Humour level"
          />

          <div className="personality-row">
            <span className="personality-label">Commentary</span>

            <select
              className="personality-select"
              value={value.commentary_frequency || "balanced"}
              onChange={(event) =>
                apply({ commentary_frequency: event.target.value })
              }
              aria-label="Commentary frequency"
            >
              {COMMENTARY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="personality-row">
            <span className="personality-label">Spoken length</span>

            <select
              className="personality-select"
              value={value.spoken_response_length || "short"}
              onChange={(event) =>
                apply({ spoken_response_length: event.target.value })
              }
              aria-label="Spoken response length"
            >
              {LENGTH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {voices.length > 0 && (
            <div className="personality-row">
              <span className="personality-label">Voice</span>

              <select
                className="personality-select"
                value={value.voice || ""}
                onChange={(event) =>
                  apply({ voice: event.target.value })
                }
                aria-label="Voice"
              >
                {voices.map((voice) => (
                  <option key={voice.name} value={voice.name}>
                    {voice.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="personality-footer">
            <button
              type="button"
              className="personality-reset"
              onClick={reset}
            >
              RESET DEFAULTS
            </button>

            {status && (
              <span className="personality-status">{status}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
