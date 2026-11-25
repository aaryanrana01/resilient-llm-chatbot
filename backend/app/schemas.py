"""Request/response models. Field names follow the assignment's API contract exactly."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 1-128 chars, and not only whitespace. The value is echoed back unchanged.
SessionId = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"\S")]
# 1-4000 chars *after* trimming whitespace.
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
SystemPrompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=8000)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: SessionId
    message: Message
    system_prompt: SystemPrompt | None = None


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None = Field(description="key_1, key_2, ... - null on LLM_CACHE. Never the key itself.")
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool
