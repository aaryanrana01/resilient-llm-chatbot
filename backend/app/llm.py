"""LiteLLM gateway: key pool with ordered auto-fallback, response cache, per-request usage.

How it fits together
--------------------
* Every API key becomes its own LiteLLM Router deployment / model group
  (``key_1``, ``key_2``, ...). The Router is configured with an ordered fallback
  chain ``key_1 -> key_2 -> ... -> key_N``. When a deployment raises (HTTP 429,
  quota, 5xx, timeout, connection error, bad key) LiteLLM moves on to the next
  key by itself.
* ``FailoverHook`` is a LiteLLM ``CustomLogger``. Its pre-call deployment hook runs
  right before LiteLLM sends a request to a specific key. It records which keys
  were attempted (to compute ``fallback_attempts``) and, when X-Simulate-Failure
  asks for it, raises the same LiteLLM exception a real provider error would
  produce - so the simulated path goes through exactly the same Router fallback
  code as a real outage.
* Responses are cached in LiteLLM's built-in ``Cache`` (in-memory). The cache key
  is LiteLLM's hash of ``model + full message list`` (system + history + new
  message). A hit never touches a provider, so it has ``key_id = None`` and
  ``fallback_attempts = 0``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm import Router
from litellm.caching.caching import Cache
from litellm.integrations.custom_logger import CustomLogger

from .config import Settings
from .simulation import simulated_error, status_for_key

logger = logging.getLogger("app.llm")

LIVE_INFERENCE = "LIVE_INFERENCE"
LLM_CACHE = "LLM_CACHE"
_TRACE_ID_FIELD = "lyftr_request_id"

# Never let LiteLLM print request bodies / keys, and drop params a model does not support.
litellm.suppress_debug_info = True
litellm.drop_params = True
litellm.telemetry = False
for _name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)


class AllProvidersUnavailable(Exception):
    """Every key in the pool failed for this request."""


@dataclass
class LLMResult:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str
    key_id: str | None
    fallback_attempts: int


@dataclass
class _RequestTrace:
    simulate: dict[str, int]
    # Keys that already answered with an empty completion in this request: skip them.
    skip: set[str] = field(default_factory=set)
    attempted_keys: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def distinct_attempts(self) -> list[str]:
        return list(dict.fromkeys(self.attempted_keys))


def _deployment_key_id(data: dict[str, Any]) -> str | None:
    model_info = data.get("model_info") or {}
    if isinstance(model_info, dict) and model_info.get("id"):
        return str(model_info["id"])
    metadata = data.get("metadata") or {}
    nested = metadata.get("model_info") or {}
    return str(nested.get("id")) if isinstance(nested, dict) and nested.get("id") else None


def _trace_id(data: Any) -> str | None:
    metadata = (data.get("metadata") if isinstance(data, dict) else None) or {}
    return metadata.get(_TRACE_ID_FIELD)


class FailoverHook(CustomLogger):
    """Per-deployment hook used for attempt tracking and failure simulation."""

    def __init__(self) -> None:
        super().__init__()
        self.traces: dict[str, _RequestTrace] = {}

    async def async_pre_call_deployment_hook(self, kwargs, call_type):  # type: ignore[override]
        trace = self.traces.get(_trace_id(kwargs) or "")
        if trace is None:
            return kwargs
        key_id = _deployment_key_id(kwargs) or "unknown"
        trace.attempted_keys.append(key_id)
        if key_id in trace.skip:
            raise litellm.InternalServerError(
                message=f"{key_id} returned an empty completion earlier in this request",
                llm_provider="unknown",
                model=str(kwargs.get("model", "")),
            )
        status = status_for_key(trace.simulate, key_id)
        if status is not None:
            trace.failures.append(f"{key_id}:{status}(simulated)")
            logger.info("simulating HTTP %s on %s", status, key_id)
            raise simulated_error(status, key_id, str(kwargs.get("model", "")))
        return kwargs

    async def async_post_call_failure_deployment_hook(self, request_data, exception, call_type, fallback_depth=None):  # type: ignore[override]
        trace = self.traces.get(_trace_id(request_data) or "")
        key_id = _deployment_key_id(dict(request_data)) or "unknown"
        status = getattr(exception, "status_code", None)
        if trace is not None:
            trace.failures.append(f"{key_id}:{status or type(exception).__name__}")
        logger.warning("provider call failed on %s: %s (HTTP %s)", key_id, type(exception).__name__, status)


_HOOK = FailoverHook()


def _register_hook() -> FailoverHook:
    callbacks = list(litellm.callbacks or [])
    if not any(cb is _HOOK for cb in callbacks):
        callbacks.append(_HOOK)
        litellm.callbacks = callbacks
    return _HOOK


def _extract_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def _usage_int(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None) if usage is not None else None
    if value is None and isinstance(usage, dict):
        value = usage.get(name)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key_ids = settings.key_ids
        self.model_by_key = dict(zip(self.key_ids, settings.models))
        self.hook = _register_hook()
        self.cache = Cache(type="local", default_in_memory_ttl=settings.cache_ttl_seconds)
        self.router: Router | None = self._build_router() if settings.api_keys else None

    @property
    def keys_configured(self) -> int:
        return len(self.key_ids)

    @property
    def cache_enabled(self) -> bool:
        return self.cache is not None

    def _build_router(self) -> Router:
        model_list = []
        for key_id, api_key in zip(self.key_ids, self.settings.api_keys):
            litellm_params: dict[str, Any] = {
                "model": self.model_by_key[key_id],
                "api_key": api_key,
                "max_retries": 0,  # fail fast: the next key is the retry
                "timeout": self.settings.llm_timeout_seconds,
            }
            if self.settings.llm_api_base:
                litellm_params["api_base"] = self.settings.llm_api_base
            model_list.append(
                {"model_name": key_id, "litellm_params": litellm_params, "model_info": {"id": key_id}}
            )
        fallbacks = [{self.key_ids[0]: self.key_ids[1:]}] if len(self.key_ids) > 1 else []
        return Router(
            model_list=model_list,
            fallbacks=fallbacks,
            max_fallbacks=len(self.key_ids),
            num_retries=0,
            # Cooldowns are off so a simulated failure on key_1 never affects the next request.
            disable_cooldowns=True,
            timeout=self.settings.llm_timeout_seconds,
        )

    # ---- cache ---------------------------------------------------------------

    def _candidate_models(self) -> list[str]:
        seen: list[str] = []
        for model in self.model_by_key.values():
            if model not in seen:
                seen.append(model)
        return seen

    async def _cache_lookup(self, messages: list[dict[str, str]]) -> LLMResult | None:
        for model in self._candidate_models():
            cached = await self.cache.async_get_cache(model=model, messages=messages)
            if isinstance(cached, dict) and cached.get("reply"):
                return LLMResult(
                    reply=cached["reply"],
                    model=cached.get("model", model),
                    input_tokens=int(cached.get("input_tokens", 0)),
                    output_tokens=int(cached.get("output_tokens", 0)),
                    resolution_source=LLM_CACHE,
                    key_id=None,
                    fallback_attempts=0,
                )
        return None

    async def _cache_store(self, messages: list[dict[str, str]], result: LLMResult) -> None:
        payload = {
            "reply": result.reply,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
        try:
            await self.cache.async_add_cache(
                payload, model=result.model, messages=messages, ttl=self.settings.cache_ttl_seconds
            )
        except Exception:  # caching must never break a successful reply
            logger.exception("failed to write response cache")

    # ---- main entry point ------------------------------------------------------

    async def complete(self, messages: list[dict[str, str]], simulate: dict[str, int] | None = None) -> LLMResult:
        simulate = simulate or {}

        # Simulation requests skip the cache *read* so the failover path is always exercised.
        if not simulate:
            cached = await self._cache_lookup(messages)
            if cached is not None:
                return cached

        if self.router is None:
            raise AllProvidersUnavailable("no API keys configured")

        trace_id = uuid.uuid4().hex
        trace = _RequestTrace(simulate=simulate)
        self.hook.traces[trace_id] = trace

        params: dict[str, Any] = {"max_tokens": self.settings.llm_max_tokens}
        if self.settings.llm_temperature is not None:
            params["temperature"] = self.settings.llm_temperature
        if self.settings.llm_reasoning_effort:
            params["reasoning_effort"] = self.settings.llm_reasoning_effort

        try:
            # Normally one Router call does everything (it walks key_1 -> key_N on errors).
            # A 200 with an empty completion is not an exception for LiteLLM, so in that rare
            # case we mark every key tried so far as "skip" and let the Router continue
            # with the keys that are left.
            while True:
                try:
                    response = await self.router.acompletion(
                        model=self.key_ids[0],
                        messages=messages,
                        metadata={_TRACE_ID_FIELD: trace_id},
                        **params,
                    )
                except Exception as exc:
                    logger.error(
                        "all providers unavailable (attempted=%s, failures=%s, last=%s)",
                        trace.distinct_attempts(), trace.failures, type(exc).__name__,
                    )
                    raise AllProvidersUnavailable(type(exc).__name__) from None

                key_id = self._answering_key(response, trace)
                reply = _extract_text(response)
                if reply:
                    break
                logger.warning("%s returned an empty completion; trying the next key", key_id)
                trace.failures.append(f"{key_id}:empty")
                trace.skip.update(trace.distinct_attempts())
                if len(trace.skip) >= len(self.key_ids):
                    raise AllProvidersUnavailable("empty completion from every key")
        finally:
            self.hook.traces.pop(trace_id, None)

        model = self.model_by_key[key_id]
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "prompt_tokens")
        output_tokens = _usage_int(usage, "completion_tokens")
        if input_tokens is None:
            input_tokens = litellm.token_counter(model=model, messages=messages)
        if output_tokens is None:
            output_tokens = litellm.token_counter(model=model, text=reply)

        attempts = trace.distinct_attempts()
        result = LLMResult(
            reply=reply,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            resolution_source=LIVE_INFERENCE,
            key_id=key_id,
            # keys that failed before the one that answered
            fallback_attempts=attempts.index(key_id) if key_id in attempts else max(len(attempts) - 1, 0),
        )
        if trace.failures:
            logger.info("answered by %s after failures: %s", key_id, trace.failures)
        await self._cache_store(messages, result)
        return result

    def _answering_key(self, response: Any, trace: _RequestTrace) -> str:
        hidden = getattr(response, "_hidden_params", {}) or {}
        key_id = hidden.get("model_id")
        if key_id in self.model_by_key:
            return str(key_id)
        attempts = trace.distinct_attempts()
        return attempts[-1] if attempts else self.key_ids[0]
