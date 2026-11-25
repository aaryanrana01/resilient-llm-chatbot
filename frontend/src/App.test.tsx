import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const health = { status: "ok", keys_configured: 2, cache_enabled: true };

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("chat UI contract", () => {
  let chatHandler: (body: Record<string, string>, headers: Headers) => Promise<Response>;
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/health")) return jsonResponse(health);
    return chatHandler(JSON.parse(String(init?.body)), new Headers(init?.headers));
  });

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
  });
  afterEach(() => cleanup());

  it("renders reply + per-request metadata with the required test ids and clears the input", async () => {
    chatHandler = (body) =>
      jsonResponse({
        session_id: body.session_id,
        reply: "The capital of France is Paris.",
        metadata: {
          resolution_source: "LIVE_INFERENCE",
          model: "groq/openai/gpt-oss-120b",
          latency_ms: 812,
          input_tokens: 42,
          output_tokens: 9,
          key_id: "key_1",
          fallback_attempts: 0,
        },
      });
    render(<App />);
    const input = screen.getByTestId("chat-input") as HTMLTextAreaElement;
    await userEvent.type(input, "What is the capital of France?");
    await userEvent.click(screen.getByTestId("send-button"));
    expect(input.value).toBe("");

    const msg = await screen.findByTestId("assistant-message");
    const q = within(msg);
    expect(msg.textContent).toContain("The capital of France is Paris.");
    expect(q.getByTestId("meta-source").textContent).toBe("LIVE_INFERENCE");
    expect(q.getByTestId("meta-model").textContent).toBe("groq/openai/gpt-oss-120b");
    expect(q.getByTestId("meta-latency").textContent).toBe("812 ms");
    expect(q.getByTestId("meta-input-tokens").textContent).toBe("42");
    expect(q.getByTestId("meta-output-tokens").textContent).toBe("9");
  });

  it("sends Enter, includes session id, system prompt and only the new message", async () => {
    const bodies: Record<string, string>[] = [];
    chatHandler = (body) => {
      bodies.push(body);
      return jsonResponse({
        session_id: body.session_id,
        reply: "ok",
        metadata: { resolution_source: "LLM_CACHE", model: "m", latency_ms: 3, input_tokens: 10, output_tokens: 1, key_id: null, fallback_attempts: 0 },
      });
    };
    render(<App />);
    await userEvent.type(screen.getByTestId("system-prompt-input"), "Be brief.");
    await userEvent.type(screen.getByTestId("chat-input"), "hello{Enter}");
    await screen.findByTestId("assistant-message");
    expect(bodies[0].message).toBe("hello");
    expect(bodies[0].system_prompt).toBe("Be brief.");
    expect(bodies[0].session_id).toMatch(/^s-/);
    expect(screen.getByTestId("meta-source").textContent).toBe("LLM_CACHE");
  });

  it("shows 503 and 422 as readable chat messages", async () => {
    render(<App />);
    chatHandler = () => jsonResponse({ detail: "all providers unavailable" }, 503);
    await userEvent.type(screen.getByTestId("chat-input"), "hi{Enter}");
    const err = await screen.findByTestId("error-message");
    expect(err.textContent).toMatch(/providers unavailable/i);

    chatHandler = () =>
      jsonResponse({ detail: [{ type: "string_too_long", loc: ["body", "message"], msg: "String should have at most 4000 characters" }] }, 422);
    await userEvent.type(screen.getByTestId("chat-input"), "x{Enter}");
    await waitFor(() => expect(screen.getAllByTestId("error-message")).toHaveLength(2));
    expect(screen.getAllByTestId("error-message")[1].textContent).toContain("at most 4000 characters");
  });

  it("forwards the failover simulator header", async () => {
    let seen: string | null = null;
    chatHandler = (body, headers) => {
      seen = headers.get("X-Simulate-Failure");
      return jsonResponse({
        session_id: body.session_id,
        reply: "ok",
        metadata: { resolution_source: "LIVE_INFERENCE", model: "m", latency_ms: 30, input_tokens: 5, output_tokens: 1, key_id: "key_2", fallback_attempts: 1 },
      });
    };
    render(<App />);
    await userEvent.selectOptions(screen.getByTestId("simulate-failure-select"), "key_1=429");
    await userEvent.type(screen.getByTestId("chat-input"), "hi{Enter}");
    await screen.findByTestId("assistant-message");
    expect(seen).toBe("key_1=429");
    expect(screen.getByTestId("meta-key-id").textContent).toBe("key_2");
  });
});
