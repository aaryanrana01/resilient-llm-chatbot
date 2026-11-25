from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fake_provider import FakeProvider

TEST_MODEL = "groq/openai/gpt-oss-120b"


@pytest.fixture(scope="session")
def provider() -> Iterator[FakeProvider]:
    fake = FakeProvider()
    fake.start()
    yield fake
    fake.stop()


@pytest.fixture
def make_settings(provider: FakeProvider, tmp_path) -> Callable[..., Settings]:
    def _make(keys: list[str] | None = None, **overrides) -> Settings:
        keys = keys or ["sk-ok-1", "sk-ok-2"]
        values = dict(
            api_keys=keys,
            models=[TEST_MODEL] * len(keys),
            database_path=str(tmp_path / "app.db"),
            allowed_origins=["http://localhost:3000"],
            enable_failure_simulation=True,
            llm_api_base=provider.base_url,
            llm_timeout_seconds=10,
        )
        values.update(overrides)
        return Settings(**values)

    return _make


@pytest.fixture
def make_client(make_settings) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(keys: list[str] | None = None, **overrides) -> TestClient:
        client = TestClient(create_app(make_settings(keys, **overrides)))
        client.__enter__()  # runs the lifespan (DB schema + gateway)
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def new_session() -> Callable[[], str]:
    return lambda: f"s-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def unique() -> Callable[[str], str]:
    """Unique message text so tests never collide on the shared response cache."""
    return lambda text: f"{text} [{uuid.uuid4().hex[:6]}]"
