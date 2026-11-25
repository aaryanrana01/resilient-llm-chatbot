"""All configuration comes from environment variables (12-factor style)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "groq/openai/gpt-oss-120b"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, friendly assistant. Answer clearly and concisely in plain text. "
    "Do not use Markdown formatting (no **bold**, # headings, tables or code fences); "
    "when a list helps, use simple numbered or dashed lines."
)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _as_float(value: str | None, default: float | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def sqlite_path_from_url(url: str) -> str:
    """Turn a DATABASE_URL into a filesystem path.

    sqlite:////data/app.db -> /data/app.db   (absolute, four slashes)
    sqlite:///./app.db     -> ./app.db       (relative, three slashes)
    A bare path is accepted as-is.
    """
    url = url.strip()
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        raise ValueError("DATABASE_URL must look like sqlite:////absolute/path.db or sqlite:///relative.db")
    return url


@dataclass(frozen=True)
class Settings:
    api_keys: list[str]
    # One model per key (same length as api_keys). Key i is served by models[i].
    models: list[str]
    database_path: str
    allowed_origins: list[str] = field(default_factory=list)
    enable_failure_simulation: bool = False
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    cache_ttl_seconds: int = 3600
    llm_timeout_seconds: float = 45.0
    llm_max_tokens: int = 2048
    llm_temperature: float | None = None
    llm_reasoning_effort: str | None = "low"
    llm_api_base: str | None = None
    max_history_messages: int = 40
    enable_api_docs: bool = False
    log_level: str = "INFO"

    @property
    def key_ids(self) -> list[str]:
        return [f"key_{i + 1}" for i in range(len(self.api_keys))]


def resolve_models(api_keys: list[str], default_model: str, per_key_models: list[str]) -> list[str]:
    """LLM_MODELS may hold one model per key; missing entries fall back to LLM_MODEL."""
    return [per_key_models[i] if i < len(per_key_models) else default_model for i in range(len(api_keys))]


def load_settings() -> Settings:
    env = os.environ
    api_keys = _split_csv(env.get("LLM_API_KEYS"))
    default_model = (env.get("LLM_MODEL") or DEFAULT_MODEL).strip()
    models = resolve_models(api_keys, default_model, _split_csv(env.get("LLM_MODELS")))

    reasoning = (env.get("LLM_REASONING_EFFORT", "low") or "").strip().lower()

    return Settings(
        api_keys=api_keys,
        models=models,
        database_path=sqlite_path_from_url(env.get("DATABASE_URL", "sqlite:///./data/app.db")),
        allowed_origins=_split_csv(env.get("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=_as_bool(env.get("ENABLE_FAILURE_SIMULATION"), False),
        default_system_prompt=(env.get("DEFAULT_SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT).strip(),
        cache_ttl_seconds=_as_int(env.get("CACHE_TTL_SECONDS"), 3600),
        llm_timeout_seconds=_as_float(env.get("LLM_TIMEOUT_SECONDS"), 45.0) or 45.0,
        llm_max_tokens=_as_int(env.get("LLM_MAX_TOKENS"), 2048),
        llm_temperature=_as_float(env.get("LLM_TEMPERATURE"), None),
        llm_reasoning_effort=reasoning if reasoning not in ("", "none", "off") else None,
        llm_api_base=(env.get("LLM_API_BASE") or "").strip() or None,
        max_history_messages=_as_int(env.get("MAX_HISTORY_MESSAGES"), 40),
        enable_api_docs=_as_bool(env.get("ENABLE_API_DOCS"), False),
        log_level=(env.get("LOG_LEVEL") or "INFO").upper(),
    )
