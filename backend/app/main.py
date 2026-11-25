"""FastAPI application: exactly three endpoints - GET /health, POST /chat, GET /sessions/{id}/messages."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import weakref
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, load_settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMGateway
from .schemas import ChatMetadata, ChatRequest, ChatResponse, HealthResponse
from .simulation import parse_simulation_header

logger = logging.getLogger("app")

ALL_PROVIDERS_UNAVAILABLE = "all providers unavailable"
SESSION_NOT_FOUND = "session not found"


class SessionLocks:
    """One asyncio.Lock per session so two requests in the same chat can't interleave history."""

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    _configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_path)
        db.init_schema()  # schema is created automatically on startup
        app.state.db = db
        app.state.gateway = LLMGateway(settings)
        app.state.locks = SessionLocks()
        if len(settings.api_keys) < 2:
            logger.warning("LLM_API_KEYS has %d key(s); at least 2 are needed for failover", len(settings.api_keys))
        logger.info(
            "started: keys=%d models=%s simulation=%s db=%s",
            len(settings.api_keys), sorted(set(settings.models)), settings.enable_failure_simulation,
            settings.database_path,
        )
        try:
            yield
        finally:
            db.close()

    docs = {} if settings.enable_api_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="LLM Chatbot API", version="1.0.0", lifespan=lifespan, **docs)
    app.state.settings = settings

    allow_all = "*" in settings.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )

    # ---- error handling: every error is JSON with a `detail` field -------------

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Same shape as FastAPI's default 422, minus the echoed input (could be 4000+ chars).
        errors = [
            {"type": e.get("type"), "loc": list(e.get("loc", [])), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    # ---- endpoints ----------------------------------------------------------

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> Any:
        db: Database = request.app.state.db
        gateway: LLMGateway = request.app.state.gateway
        db_ok = await asyncio.to_thread(db.ping)
        keys = gateway.keys_configured
        body = {"status": "ok", "keys_configured": keys, "cache_enabled": gateway.cache_enabled}
        if not db_ok or keys == 0:
            reason = "database unreachable" if not db_ok else "no API keys configured"
            return JSONResponse({**body, "status": "unavailable", "detail": reason}, status_code=503)
        return body

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        request: Request,
        x_simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
    ) -> Any:
        started = time.perf_counter()
        db: Database = request.app.state.db
        gateway: LLMGateway = request.app.state.gateway
        simulate = parse_simulation_header(x_simulate_failure) if settings.enable_failure_simulation else {}
        override = body.system_prompt or None  # "" / whitespace -> no override

        async with request.app.state.locks.get(body.session_id):
            try:
                session = await asyncio.to_thread(db.get_session, body.session_id)
                history = await asyncio.to_thread(
                    db.get_recent_history, body.session_id, settings.max_history_messages
                )
            except Exception:
                logger.exception("failed to load session %s", body.session_id)
                raise HTTPException(status_code=500, detail="could not load session history") from None

            system_prompt = override or (session.system_prompt if session else None) or settings.default_system_prompt
            messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": body.message}]

            try:
                result = await gateway.complete(messages, simulate)
            except AllProvidersUnavailable:
                raise HTTPException(status_code=503, detail=ALL_PROVIDERS_UNAVAILABLE) from None
            except Exception:
                logger.exception("unexpected LLM gateway error")
                raise HTTPException(status_code=503, detail=ALL_PROVIDERS_UNAVAILABLE) from None

            # whole milliseconds, rounded up so a sub-millisecond cache hit reads 1 ms, not 0
            latency_ms = max(1, math.ceil((time.perf_counter() - started) * 1000))
            metadata = ChatMetadata(
                resolution_source=result.resolution_source,  # type: ignore[arg-type]
                model=result.model,
                latency_ms=latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                key_id=result.key_id,
                fallback_attempts=result.fallback_attempts,
            )
            try:
                await asyncio.to_thread(
                    db.save_exchange, body.session_id, body.message, result.reply, metadata.model_dump(), override
                )
            except Exception:
                logger.exception("failed to save exchange for session %s", body.session_id)
                raise HTTPException(status_code=500, detail="could not save message history") from None

        return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)

    @app.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str, request: Request) -> Any:
        db: Database = request.app.state.db
        messages = await asyncio.to_thread(db.list_messages, session_id)
        if not messages:
            raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
        return {"session_id": session_id, "messages": messages}

    return app


app = create_app()
