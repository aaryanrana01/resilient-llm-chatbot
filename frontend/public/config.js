// Runtime configuration. The Docker image rewrites this file at container start
// from the API_BASE_URL environment variable. Empty values fall back to the
// build-time VITE_API_BASE_URL, then to http://localhost:8000.
window.__APP_CONFIG__ = { API_BASE_URL: "" };
