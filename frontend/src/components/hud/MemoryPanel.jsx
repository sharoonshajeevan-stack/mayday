// src/components/hud/MemoryPanel.jsx
//
// The Memory section of MAYDAY's HUD. It talks to the backend's persistent
// long-term memory store (SQLite, backend/memory/mayday_memory.db) so the user
// can inspect, search, add, edit, delete and export what MAYDAY remembers -
// and switch automatic memory creation / retrieval on or off.
//
// It never redesigns the HUD: it is a compact panel toggled by one button,
// matching the Personality settings panel next to it.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getLongTermMemories,
  createLongTermMemory,
  updateLongTermMemory,
  deleteLongTermMemory,
  clearLongTermMemories,
  getMemorySettings,
  updateMemorySettings,
  exportLongTermMemories,
} from "../../services/api";

import "./MemoryPanel.css";

const CATEGORY_OPTIONS = [
  { value: "", label: "All" },
  { value: "preference", label: "Preferences" },
  { value: "user", label: "User info" },
  { value: "project", label: "Projects" },
  { value: "conversation", label: "Conversations" },
  { value: "task", label: "Tasks" },
  { value: "technical", label: "Technical" },
];

const NEW_MEMORY_CATEGORIES = CATEGORY_OPTIONS.filter((option) => option.value);

function formatTimestamp(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

export default function MemoryPanel() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [memories, setMemories] = useState([]);
  const [total, setTotal] = useState(0);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const [draft, setDraft] = useState("");
  const [draftCategory, setDraftCategory] = useState("user");
  const [editingId, setEditingId] = useState(null);
  const [editingText, setEditingText] = useState("");

  const searchTimer = useRef(null);

  const load = useCallback(
    async (options = {}) => {
      setBusy(true);

      const result = await getLongTermMemories({
        category: options.category ?? category,
        q: options.q ?? query,
        limit: 200,
      });

      setBusy(false);

      if (result?.success) {
        setMemories(result.data?.memories || []);
        setTotal(result.data?.total ?? 0);
      } else {
        setStatus("Could not load memories");
      }
    },
    [category, query],
  );

  const loadSettings = useCallback(async () => {
    const result = await getMemorySettings();

    if (result?.success) {
      setSettings(result.data?.settings || {});
    }
  }, []);

  useEffect(() => {
    // Mirror the Personality panel: load from the backend on mount.
    getMemorySettings().then((result) => {
      if (result?.success) {
        setSettings(result.data?.settings || {});
      }
    });

    getLongTermMemories({ limit: 200 }).then((result) => {
      if (result?.success) {
        setMemories(result.data?.memories || []);
        setTotal(result.data?.total ?? 0);
      }
    });

    return () => {
      if (searchTimer.current) {
        clearTimeout(searchTimer.current);
      }
    };
  }, []);

  const onQueryChange = (value) => {
    setQuery(value);

    if (searchTimer.current) {
      clearTimeout(searchTimer.current);
    }

    searchTimer.current = setTimeout(() => {
      load({ q: value });
    }, 350);
  };

  const onCategoryChange = (value) => {
    setCategory(value);
    load({ category: value });
  };

  const toggleSetting = async (key, value) => {
    setSettings((prev) => ({ ...(prev || {}), [key]: value }));

    const result = await updateMemorySettings({ [key]: value });

    if (result?.success) {
      setSettings(result.data?.settings || settings);
      setStatus("Saved");
    } else {
      setStatus("Save failed");
      loadSettings();
    }
  };

  const addMemory = async () => {
    const content = draft.trim();

    if (!content) {
      return;
    }

    const result = await createLongTermMemory({
      content,
      category: draftCategory,
      tags: ["manual"],
    });

    if (result?.success) {
      setDraft("");
      setStatus("Memory saved");
      load({ category, q: query });
    } else {
      setStatus(result?.error || "Could not save memory");
    }
  };

  const startEdit = (memory) => {
    setEditingId(memory.id);
    setEditingText(memory.content);
  };

  const saveEdit = async () => {
    const content = editingText.trim();

    if (!editingId || !content) {
      return;
    }

    const result = await updateLongTermMemory(editingId, { content });

    if (result?.success) {
      setEditingId(null);
      setEditingText("");
      setStatus("Memory updated");
      load({ category, q: query });
    } else {
      setStatus(result?.error || "Could not update memory");
    }
  };

  const removeMemory = async (memory) => {
    if (!window.confirm("Delete this memory?")) {
      return;
    }

    const result = await deleteLongTermMemory(memory.id);

    if (result?.success) {
      setStatus("Memory deleted");
      load({ category, q: query });
    } else {
      setStatus(result?.error || "Could not delete memory");
    }
  };

  const clearAll = async () => {
    const confirmation = window.prompt(
      'This deletes every saved memory. Type "clear" to confirm.',
    );

    if (confirmation !== "clear") {
      return;
    }

    const result = await clearLongTermMemories();

    if (result?.success) {
      setStatus(`Cleared ${result.data?.removed ?? 0} memories`);
      load({ category, q: query });
    } else {
      setStatus(result?.error || "Could not clear memories");
    }
  };

  const exportAll = async () => {
    const result = await exportLongTermMemories();

    if (!result?.success) {
      setStatus("Export failed");
      return;
    }

    const blob = new Blob([JSON.stringify(result.data, null, 2)], {
      type: "application/json",
    });

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `mayday-memory-${new Date()
      .toISOString()
      .slice(0, 10)}.json`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setStatus("Exported");
  };

  const value = settings || {};

  return (
    <div className="memory-panel-root">
      <button
        type="button"
        className={`memory-toggle ${open ? "open" : ""}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Toggle memory panel"
        aria-expanded={open}
      >
        <span className="memory-toggle-icon" aria-hidden="true">
          &#9679;
        </span>
        <span className="memory-toggle-label">MEMORY</span>
        {total > 0 && <span className="memory-toggle-count">{total}</span>}
      </button>

      {open && (
        <div className="memory-panel" role="dialog" aria-label="Memory">
          <div className="memory-panel-header">
            <span>MEMORY</span>

            <button
              type="button"
              className="memory-close"
              onClick={() => setOpen(false)}
              aria-label="Close memory panel"
            >
              &times;
            </button>
          </div>

          <div className="memory-settings">
            <label className="memory-switch">
              <input
                type="checkbox"
                checked={Boolean(value.auto_capture)}
                onChange={(event) =>
                  toggleSetting("auto_capture", event.target.checked)
                }
              />
              <span>Remember automatically</span>
            </label>

            <label className="memory-switch">
              <input
                type="checkbox"
                checked={Boolean(value.retrieval_enabled)}
                onChange={(event) =>
                  toggleSetting("retrieval_enabled", event.target.checked)
                }
              />
              <span>Use memories in replies</span>
            </label>

            <label className="memory-switch">
              <input
                type="checkbox"
                checked={Boolean(value.summarize_enabled)}
                onChange={(event) =>
                  toggleSetting("summarize_enabled", event.target.checked)
                }
              />
              <span>Summarise long conversations</span>
            </label>
          </div>

          <div className="memory-toolbar">
            <select
              className="memory-select"
              value={category}
              onChange={(event) => onCategoryChange(event.target.value)}
              aria-label="Filter by category"
            >
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>

            <input
              className="memory-search"
              type="search"
              placeholder="Search memories..."
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              aria-label="Search memories"
            />
          </div>

          <div className="memory-add">
            <textarea
              className="memory-textarea"
              rows="2"
              placeholder="Add a memory (e.g. my project uses React and Python)"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />

            <div className="memory-add-row">
              <select
                className="memory-select"
                value={draftCategory}
                onChange={(event) => setDraftCategory(event.target.value)}
                aria-label="New memory category"
              >
                {NEW_MEMORY_CATEGORIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <button
                type="button"
                className="memory-button"
                onClick={addMemory}
                disabled={!draft.trim()}
              >
                SAVE
              </button>
            </div>
          </div>

          <div className="memory-list">
            {busy && <div className="memory-empty">Loading...</div>}

            {!busy && memories.length === 0 && (
              <div className="memory-empty">
                Nothing remembered here yet.
              </div>
            )}

            {!busy &&
              memories.map((memory) => (
                <div key={memory.id} className="memory-item">
                  <div className="memory-item-head">
                    <span className="memory-badge">{memory.category}</span>
                    <span className="memory-timestamps">
                      {formatTimestamp(memory.updated_at)}
                    </span>
                  </div>

                  {editingId === memory.id ? (
                    <>
                      <textarea
                        className="memory-textarea"
                        rows="2"
                        value={editingText}
                        onChange={(event) =>
                          setEditingText(event.target.value)
                        }
                      />

                      <div className="memory-item-actions">
                        <button
                          type="button"
                          className="memory-button"
                          onClick={saveEdit}
                        >
                          SAVE
                        </button>
                        <button
                          type="button"
                          className="memory-button ghost"
                          onClick={() => setEditingId(null)}
                        >
                          CANCEL
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="memory-content">{memory.content}</div>

                      <div className="memory-item-actions">
                        <button
                          type="button"
                          className="memory-link"
                          onClick={() => startEdit(memory)}
                        >
                          EDIT
                        </button>
                        <button
                          type="button"
                          className="memory-link danger"
                          onClick={() => removeMemory(memory)}
                        >
                          DELETE
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))}
          </div>

          <div className="memory-footer">
            <button
              type="button"
              className="memory-button ghost"
              onClick={exportAll}
            >
              EXPORT
            </button>

            <button
              type="button"
              className="memory-button danger"
              onClick={clearAll}
            >
              CLEAR ALL
            </button>

            {status && <span className="memory-status">{status}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
