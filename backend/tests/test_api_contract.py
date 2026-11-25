"""/health, /chat validation (422) and the error-shape rules."""

from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_health_reports_every_key(make_client):
    c = make_client(["sk-ok-1", "sk-ok-2", "sk-ok-3"])
    assert c.get("/health").json()["keys_configured"] == 3


def test_health_unavailable_without_keys(make_client):
    c = make_client(keys=None, api_keys=[], models=[])
    r = c.get("/health")
    assert r.status_code == 503
    assert "detail" in r.json()


def test_chat_response_shape(client, new_session, unique):
    sid = new_session()
    r = client.post("/chat", json={"session_id": sid, "message": unique("What is the capital of France?")})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert isinstance(body["reply"], str) and body["reply"].strip()
    meta = body["metadata"]
    assert set(meta) >= {
        "resolution_source", "model", "latency_ms", "input_tokens", "output_tokens", "key_id", "fallback_attempts"
    }
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "groq/openai/gpt-oss-120b"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] > 0
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_api_key_never_leaks(client, new_session, unique):
    r = client.post("/chat", json={"session_id": new_session(), "message": unique("hi")})
    assert "sk-ok" not in r.text
    assert "sk-ok" not in client.get("/health").text


# ---- 422 validation ---------------------------------------------------------

def _assert_422(r):
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_missing_message(client, new_session):
    _assert_422(client.post("/chat", json={"session_id": new_session()}))


def test_missing_session_id(client):
    _assert_422(client.post("/chat", json={"message": "hello"}))


def test_empty_and_whitespace_message(client, new_session):
    _assert_422(client.post("/chat", json={"session_id": new_session(), "message": ""}))
    _assert_422(client.post("/chat", json={"session_id": new_session(), "message": "   \n\t "}))


def test_empty_session_id(client):
    _assert_422(client.post("/chat", json={"session_id": "", "message": "hello"}))
    _assert_422(client.post("/chat", json={"session_id": "   ", "message": "hello"}))


def test_session_id_too_long(client):
    _assert_422(client.post("/chat", json={"session_id": "s" * 129, "message": "hello"}))
    ok = client.post("/chat", json={"session_id": "s" * 128, "message": "hello 128"})
    assert ok.status_code == 200


def test_message_length_limits(client, new_session):
    _assert_422(client.post("/chat", json={"session_id": new_session(), "message": "a" * 4001}))
    # 4000 chars of content plus surrounding whitespace is fine (limit applies after trimming)
    ok = client.post("/chat", json={"session_id": new_session(), "message": "  " + "a" * 4000 + "  "})
    assert ok.status_code == 200


def test_wrong_types(client, new_session):
    _assert_422(client.post("/chat", json={"session_id": new_session(), "message": 123}))
    _assert_422(client.post("/chat", json={"session_id": 42, "message": "hi"}))


def test_malformed_json(client):
    r = client.post("/chat", content=b'{"session_id": "s-1", "message": ', headers={"content-type": "application/json"})
    _assert_422(r)


def test_failed_request_not_added_to_history(client, new_session):
    sid = new_session()
    client.post("/chat", json={"session_id": sid, "message": "a" * 5000})
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_unknown_route_is_json(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_only_contract_endpoints_exposed(client):
    # API docs are off by default ("exactly these three endpoints")
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cors_allows_frontend_origin_and_simulation_header(client):
    r = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "x-simulate-failure" in r.headers["access-control-allow-headers"].lower()


def test_cors_rejects_other_origins(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
