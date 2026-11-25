declare global {
  interface Window {
    __APP_CONFIG__?: { API_BASE_URL?: string };
  }
}

/**
 * Where the backend lives. Order of precedence:
 * 1. window.__APP_CONFIG__.API_BASE_URL - written at container start (Docker, from API_BASE_URL)
 * 2. VITE_API_BASE_URL - baked in at build time (static hosts like Render / Vercel / Netlify)
 * 3. http://localhost:8000 - local development default
 */
export function apiBaseUrl(): string {
  const runtime = typeof window !== "undefined" ? window.__APP_CONFIG__?.API_BASE_URL : undefined;
  const value = runtime || import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
  return value.replace(/\/+$/, "");
}

export function newSessionId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 12)
      : Math.random().toString(16).slice(2, 14);
  return `s-${random}`;
}
