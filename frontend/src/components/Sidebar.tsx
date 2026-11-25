import { useState } from "react";
import type { HealthResponse } from "../types";

export type HealthState =
  | { state: "checking" }
  | { state: "online"; health: HealthResponse }
  | { state: "offline"; message: string };

const SIM_PRESETS = [
  { value: "", label: "Off — normal requests" },
  { value: "key_1=429", label: "key_1 → 429 (rate limit)" },
  { value: "key_1=500", label: "key_1 → 500 (server error)" },
  { value: "key_1=429,key_2=500", label: "key_1 → 429, key_2 → 500" },
  { value: "*=429", label: "every key → 429 (expect 503)" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  onNewChat: () => void;
  health: HealthState;
  apiUrl: string;
  systemPrompt: string;
  onSystemPromptChange: (value: string) => void;
  simulateFailure: string;
  onSimulateFailureChange: (value: string) => void;
  stats: { replies: number; cacheHits: number; failovers: number };
}

export function Sidebar(props: Props) {
  const { health } = props;
  const isPreset = SIM_PRESETS.some((p) => p.value === props.simulateFailure);
  const [custom, setCustom] = useState(!isPreset);

  return (
    <aside className={`sidebar ${props.open ? "is-open" : ""}`} aria-label="Session settings">
      <div className="sidebar__head">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <div>
            <h1 className="brand__name">Relay Chat</h1>
            <p className="brand__tag">LLM gateway · key failover · response cache</p>
          </div>
        </div>
        <button className="icon-btn sidebar__close" onClick={props.onClose} aria-label="Close settings">
          ×
        </button>
      </div>

      <section className="panel">
        <h2 className="panel__title">Backend</h2>
        <StatusLine health={health} />
        <p className="panel__mono" title={props.apiUrl}>
          {props.apiUrl}
        </p>
      </section>

      <section className="panel">
        <div className="panel__row">
          <h2 className="panel__title">Session</h2>
          <button className="btn btn--ghost" onClick={props.onNewChat} data-testid="new-chat-button">
            New chat
          </button>
        </div>
        <p className="panel__mono" data-testid="session-id">
          {props.sessionId}
        </p>
        <ul className="stats">
          <li>
            <strong>{props.stats.replies}</strong> replies
          </li>
          <li>
            <strong>{props.stats.cacheHits}</strong> cache hits
          </li>
          <li>
            <strong>{props.stats.failovers}</strong> with failover
          </li>
        </ul>
      </section>

      <section className="panel">
        <label className="panel__title" htmlFor="system-prompt">
          System prompt
        </label>
        <textarea
          id="system-prompt"
          data-testid="system-prompt-input"
          className="field field--area"
          placeholder="e.g. You are a friendly travel guide. Keep answers under 80 words."
          value={props.systemPrompt}
          onChange={(e) => props.onSystemPromptChange(e.target.value)}
          rows={4}
        />
        <p className="hint">Sent with each message and overrides the default prompt for this session. Leave empty to use the default.</p>
      </section>

      <section className="panel">
        <label className="panel__title" htmlFor="sim-select">
          Failover simulator
        </label>
        <select
          id="sim-select"
          className="field"
          data-testid="simulate-failure-select"
          value={custom ? "__custom" : props.simulateFailure}
          onChange={(e) => {
            if (e.target.value === "__custom") {
              setCustom(true);
              return;
            }
            setCustom(false);
            props.onSimulateFailureChange(e.target.value);
          }}
        >
          {SIM_PRESETS.map((p) => (
            <option key={p.value || "off"} value={p.value}>
              {p.label}
            </option>
          ))}
          <option value="__custom">Custom header…</option>
        </select>
        {custom && (
          <input
            className="field field--mono"
            data-testid="simulate-failure-input"
            placeholder="key_1=429,key_2=503"
            value={props.simulateFailure}
            onChange={(e) => props.onSimulateFailureChange(e.target.value)}
          />
        )}
        <p className="hint">
          Adds the <code>X-Simulate-Failure</code> header to your requests so you can watch the backend fail over. Only works
          when the backend runs with <code>ENABLE_FAILURE_SIMULATION=true</code>.
        </p>
      </section>
    </aside>
  );
}

function StatusLine({ health }: { health: HealthState }) {
  if (health.state === "checking") {
    return (
      <p className="status status--checking" data-testid="health-status">
        <span className="dot" /> Connecting… (a free-tier server can take ~30 s to wake up)
      </p>
    );
  }
  if (health.state === "offline") {
    return (
      <p className="status status--offline" data-testid="health-status">
        <span className="dot" /> Unreachable — {health.message}
      </p>
    );
  }
  const { keys_configured, cache_enabled } = health.health;
  return (
    <p className="status status--online" data-testid="health-status">
      <span className="dot" /> Online · {keys_configured} key{keys_configured === 1 ? "" : "s"} in pool · cache{" "}
      {cache_enabled ? "on" : "off"}
    </p>
  );
}
