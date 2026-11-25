"""A tiny OpenAI-compatible provider used by the tests.

LiteLLM talks to it over real HTTP (via LLM_API_BASE), so the tests exercise LiteLLM's
real error mapping and Router fallback - not mocks. Behaviour is chosen by the API key:

  ...-ok...     -> 200 with a deterministic reply and usage
  ...-429...    -> 429 rate limit          ...-quota... -> 429 insufficient_quota
  ...-500/502/503... -> that 5xx status    ...-401...   -> 401 invalid key
  ...-empty...  -> 200 with empty content
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

LIVE_DELAY_SECONDS = 0.15


def count_prompt_tokens(messages: list[dict]) -> int:
    return sum(len(str(m.get("content", "")).split()) + 4 for m in messages)


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.app = FastAPI()
        self.app.add_api_route("/{path:path}", self._handle, methods=["POST"])
        self.port = _free_port()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    async def _handle(self, path: str, request: Request):
        api_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        body = await request.json()
        self.requests.append({"path": path, "api_key": api_key, "body": body})

        for code in (429, 500, 502, 503, 401, 400, 404):
            if f"-{code}" in api_key:
                return JSONResponse({"error": {"message": f"fake {code}", "code": code}}, status_code=code)
        if "-quota" in api_key:
            return JSONResponse(
                {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}},
                status_code=429,
            )

        await asyncio.sleep(LIVE_DELAY_SECONDS)
        messages = body["messages"]
        user_turns = [m["content"] for m in messages if m["role"] == "user"]
        if "-empty" in api_key:
            content = ""
        else:
            earlier = user_turns[-2] if len(user_turns) > 1 else "nothing"
            content = f"You said: {user_turns[-1]} | earlier: {earlier} | turns: {len(user_turns)}"
        return {
            "id": f"chatcmpl-{len(self.requests)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body["model"],
            "service_tier": "on_demand",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": count_prompt_tokens(messages),
                "completion_tokens": len(content.split()),
                "total_tokens": count_prompt_tokens(messages) + len(content.split()),
            },
        }

    def start(self) -> None:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake provider did not start")
            time.sleep(0.02)

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
