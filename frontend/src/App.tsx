import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getHealth, sendChat } from "./api";
import { AssistantMessage } from "./components/AssistantMessage";
import { Composer } from "./components/Composer";
import { Sidebar, type HealthState } from "./components/Sidebar";
import { apiBaseUrl, newSessionId } from "./config";
import type { ChatItem } from "./types";

const SUGGESTIONS = [
  "What is the capital of France?",
  "Explain API rate limiting in two sentences.",
  "Give me three tips for a good demo video.",
];

let counter = 0;
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

export default function App() {
  // A brand-new session on every page load.
  const [sessionId, setSessionId] = useState(newSessionId);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulateFailure, setSimulateFailure] = useState("");
  const [health, setHealth] = useState<HealthState>({ state: "checking" });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // Health check; retries while a sleeping free-tier backend wakes up.
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      attempts += 1;
      try {
        const h = await getHealth();
        if (!cancelled) setHealth({ state: "online", health: h });
      } catch (err) {
        if (cancelled) return;
        if (attempts < 12) {
          timer = setTimeout(check, 5000);
        } else {
          setHealth({ state: "offline", message: err instanceof ApiError ? err.title : "no response" });
        }
      }
    };
    check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy]);

  const send = useCallback(
    async (text: string) => {
      if (busy) return;
      const userId = nextId();
      // Blank input is still sent so the server's 422 is shown, but no empty bubble is drawn.
      if (text.trim()) {
        setItems((prev) => [...prev, { kind: "user", id: userId, content: text, status: "sending" }]);
      }
      setDraft(""); // input is empty right after sending
      setBusy(true);
      try {
        const res = await sendChat({ sessionId, message: text, systemPrompt, simulateFailure });
        setItems((prev) => [
          ...prev.map((it) => (it.id === userId && it.kind === "user" ? { ...it, status: "sent" as const } : it)),
          { kind: "assistant", id: nextId(), content: res.reply, metadata: res.metadata },
        ]);
        if (health.state !== "online") {
          getHealth()
            .then((h) => setHealth({ state: "online", health: h }))
            .catch(() => undefined);
        }
      } catch (err) {
        const e =
          err instanceof ApiError ? err : new ApiError("Something went wrong", "Unexpected error while sending. Please retry.");
        setItems((prev) => [
          ...prev.map((it) => (it.id === userId && it.kind === "user" ? { ...it, status: "failed" as const } : it)),
          { kind: "error", id: nextId(), title: e.title, message: e.message, status: e.status, retryText: text },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, sessionId, systemPrompt, simulateFailure, health.state],
  );

  const newChat = () => {
    setSessionId(newSessionId());
    setItems([]);
    setDraft("");
    setSidebarOpen(false);
  };

  const stats = useMemo(() => {
    const replies = items.filter((i) => i.kind === "assistant");
    return {
      replies: replies.length,
      cacheHits: replies.filter((r) => r.kind === "assistant" && r.metadata.resolution_source === "LLM_CACHE").length,
      failovers: replies.filter((r) => r.kind === "assistant" && r.metadata.fallback_attempts > 0).length,
    };
  }, [items]);

  return (
    <div className="layout">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessionId={sessionId}
        onNewChat={newChat}
        health={health}
        apiUrl={apiBaseUrl()}
        systemPrompt={systemPrompt}
        onSystemPromptChange={setSystemPrompt}
        simulateFailure={simulateFailure}
        onSimulateFailureChange={setSimulateFailure}
        stats={stats}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}

      <main className="chat">
        <header className="topbar">
          <button className="icon-btn topbar__menu" onClick={() => setSidebarOpen(true)} aria-label="Open settings">
            <span />
            <span />
            <span />
          </button>
          <div className="topbar__title">
            <span className="brand__mark brand__mark--sm" aria-hidden="true" />
            Relay Chat
          </div>
          <button className="btn btn--ghost topbar__new" onClick={newChat}>
            New chat
          </button>
        </header>

        <div className="thread" aria-live="polite">
          {items.length === 0 ? (
            <div className="empty">
              <h2>Start a conversation</h2>
              <p>
                Every reply shows where it came from (<b>LIVE_INFERENCE</b> or <b>LLM_CACHE</b>), the model, latency and the
                tokens of that request. Send the same first message in a new chat to see a cache hit.
              </p>
              <div className="chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            items.map((item) => {
              if (item.kind === "user") {
                return (
                  <div key={item.id} className={`msg msg--user ${item.status === "failed" ? "is-failed" : ""}`} data-testid="user-message">
                    <div className="msg__text">{item.content}</div>
                    {item.status === "failed" && <span className="msg__note">not saved</span>}
                  </div>
                );
              }
              if (item.kind === "assistant") {
                return <AssistantMessage key={item.id} content={item.content} metadata={item.metadata} />;
              }
              return (
                <div key={item.id} className="msg msg--error" role="alert" data-testid="error-message">
                  <div className="msg__avatar msg__avatar--error" aria-hidden="true">
                    !
                  </div>
                  <div className="msg__body">
                    <p className="msg__error-title">
                      {item.title}
                      {item.status ? <span className="code-pill">{item.status}</span> : null}
                    </p>
                    <p className="msg__error-text">{item.message}</p>
                    {item.retryText !== undefined && (
                      <button className="btn btn--small" onClick={() => send(item.retryText!)} disabled={busy}>
                        Retry
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
          {busy && (
            <div className="msg msg--assistant msg--typing" aria-label="Assistant is typing">
              <div className="msg__avatar" aria-hidden="true">
                AI
              </div>
              <div className="typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <Composer value={draft} onChange={setDraft} onSend={() => send(draft)} busy={busy} simulateFailure={simulateFailure} />
      </main>
    </div>
  );
}
