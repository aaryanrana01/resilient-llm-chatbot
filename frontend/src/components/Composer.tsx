import { useEffect, useRef, type KeyboardEvent } from "react";

const MAX_CHARS = 4000;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  simulateFailure: string;
}

export function Composer({ value, onChange, onSend, busy, simulateFailure }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const length = value.trim().length;

  // grow with content, up to a limit
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (!busy) onSend();
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (!busy) onSend();
      }}
    >
      {simulateFailure && (
        <p className="composer__sim" role="status">
          Failure simulation on: <code>X-Simulate-Failure: {simulateFailure}</code>
        </p>
      )}
      <div className="composer__box">
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-input"
          ref={ref}
          data-testid="chat-input"
          className="composer__input"
          placeholder="Ask anything…  (Enter to send, Shift+Enter for a new line)"
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
        />
        <button type="submit" className="composer__send" data-testid="send-button" disabled={busy} aria-label="Send message">
          {busy ? <span className="spinner" aria-hidden="true" /> : <SendIcon />}
          <span className="composer__send-label">{busy ? "Sending" : "Send"}</span>
        </button>
      </div>
      <div className="composer__foot">
        <span className={length > MAX_CHARS ? "is-over" : ""}>
          {length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
        </span>
      </div>
    </form>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path d="M4 12l16-8-6 16-2.5-6.5L4 12z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}
