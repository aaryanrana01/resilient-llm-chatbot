"""Response caching (LLM_CACHE vs LIVE_INFERENCE) and per-request token accounting."""

from __future__ import annotations

from tests.fake_provider import count_prompt_tokens


def _chat(client, sid, message, **extra):
    r = client.post("/chat", json={"session_id": sid, "message": message, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_same_first_message_in_new_session_is_cache_hit(client, new_session, unique, provider):
    msg = unique("What is the capital of France?")
    first = _chat(client, new_session(), msg)
    calls_before = len(provider.requests)
    second = _chat(client, new_session(), msg)

    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]  # identical text
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    # tokens are the usage stored with the cached response
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]
    assert second["metadata"]["model"] == first["metadata"]["model"]
    # faster than the live call and no provider request was made
    assert second["metadata"]["latency_ms"] < first["metadata"]["latency_ms"]
    assert len(provider.requests) == calls_before


def test_different_message_never_from_cache(client, new_session, unique):
    base = unique("Tell me about Paris")
    _chat(client, new_session(), base)
    for variant in (base + "!", base.lower(), base + " please"):
        assert _chat(client, new_session(), variant)["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_key_includes_history(client, new_session, unique):
    """The same text as a *second* turn has a different message list -> not a cache hit."""
    q = unique("What about Germany?")
    _chat(client, new_session(), q)
    sid = new_session()
    _chat(client, sid, unique("Hello"))
    assert _chat(client, sid, q)["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_key_includes_system_prompt(client, new_session, unique):
    q = unique("Say hi")
    _chat(client, new_session(), q)
    other = _chat(client, new_session(), q, system_prompt="You are a pirate.")
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_hit_is_still_stored_in_history(client, new_session, unique):
    msg = unique("cached question")
    _chat(client, new_session(), msg)
    sid = new_session()
    _chat(client, sid, msg)
    history = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_tokens_are_per_request_not_running_total(client, new_session, unique, provider):
    sid = new_session()
    t1 = _chat(client, sid, unique("one two three"))["metadata"]
    t2 = _chat(client, sid, unique("four five six"))["metadata"]
    t3 = _chat(client, sid, unique("seven eight nine"))["metadata"]
    # each request reports exactly what the provider billed for *that* call
    last_body = provider.requests[-1]["body"]
    assert t3["input_tokens"] == count_prompt_tokens(last_body["messages"])
    # prompt grows with history, but output tokens are just this reply
    assert t1["input_tokens"] < t2["input_tokens"] < t3["input_tokens"]
    assert t3["output_tokens"] < t1["input_tokens"] + t2["input_tokens"] + t3["input_tokens"]


def test_equal_length_first_messages_report_same_input_tokens(client, new_session):
    a = _chat(client, new_session(), "alpha beta gamma delta")["metadata"]
    b = _chat(client, new_session(), "omega sigma kappa theta")["metadata"]
    assert a["resolution_source"] == b["resolution_source"] == "LIVE_INFERENCE"
    assert a["input_tokens"] == b["input_tokens"]
