import { apiBaseUrl } from "./config";
import type { ChatResponse, HealthResponse } from "./types";

/** An error the UI can show as a readable chat message. */
export class ApiError extends Error {
  constructor(
    public readonly title: string,
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((issue: ValidationIssue) => {
        const field = (issue.loc ?? []).filter((part) => part !== "body").join(".");
        return field ? `${field}: ${issue.msg ?? "invalid"}` : (issue.msg ?? "invalid input");
      })
      .join("; ");
  }
  return "Unexpected error";
}

function errorFor(status: number, detail: unknown): ApiError {
  const text = describeDetail(detail);
  if (status === 422) {
    return new ApiError(
      "Message not accepted",
      `The server rejected this request (422) — ${text}.` +
        (text.includes("message") ? " Messages must be 1–4000 characters (spaces at the ends don't count)." : ""),
      status,
    );
  }
  if (status === 503) {
    return new ApiError(
      "All providers unavailable",
      "Every API key in the pool failed for this request (rate limit, quota or server error), " +
        "so no reply was generated (503). Nothing was saved to this chat — you can retry.",
      status,
    );
  }
  return new ApiError(`Request failed (${status})`, text, status);
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 90_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, { ...init, signal: controller.signal });
  } catch {
    throw new ApiError(
      "Can't reach the server",
      `No response from ${apiBaseUrl()}. If the backend is on a free host it may be waking up — wait a few seconds and retry.`,
    );
  } finally {
    clearTimeout(timer);
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : response.statusText;
    throw errorFor(response.status, detail);
  }
  return body as T;
}

export interface SendOptions {
  sessionId: string;
  message: string;
  systemPrompt?: string;
  simulateFailure?: string;
}

export function sendChat({ sessionId, message, systemPrompt, simulateFailure }: SendOptions): Promise<ChatResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (simulateFailure?.trim()) headers["X-Simulate-Failure"] = simulateFailure.trim();
  const payload: Record<string, string> = { session_id: sessionId, message };
  if (systemPrompt?.trim()) payload.system_prompt = systemPrompt.trim();
  return request<ChatResponse>("/chat", { method: "POST", headers, body: JSON.stringify(payload) });
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health", {}, 60_000);
}
