export type ResolutionSource = "LIVE_INFERENCE" | "LLM_CACHE";

export interface ChatMetadata {
  resolution_source: ResolutionSource;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id: string | null;
  fallback_attempts: number;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  metadata: ChatMetadata;
}

export interface HealthResponse {
  status: string;
  keys_configured: number;
  cache_enabled: boolean;
}

export type ChatItem =
  | { kind: "user"; id: string; content: string; status: "sending" | "sent" | "failed" }
  | { kind: "assistant"; id: string; content: string; metadata: ChatMetadata }
  | { kind: "error"; id: string; title: string; message: string; status?: number; retryText?: string };
