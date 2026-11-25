"""Key pool failover: real provider errors and the X-Simulate-Failure hook."""

from __future__ import annotations

import pytest

from app.simulation import parse_simulation_header


def _post(client, sid, message, header=None):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": sid, "message": message}, headers=headers)


# ---- X-Simulate-Failure ---------------------------------------------------

@pytest.mark.parametrize("header", ["key_1=429", "key_1=500", "key_1=502", "key_1=503"])
def test_simulated_failure_on_key_1_falls_back_to_key_2(client, new_session, unique, header):
    r = _post(client, new_session(), unique("hello"), header)
    assert r.status_code == 200, r.text
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert "You said:" in r.json()["reply"]  # a real answer, not an error wrapped in a 200


def test_two_keys_fail_third_answers(make_client, new_session, unique):
    c = make_client(["sk-ok-1", "sk-ok-2", "sk-ok-3"])
    r = _post(c, new_session(), unique("hello"), "key_1=429,key_2=500")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_3"
    assert r.json()["metadata"]["fallback_attempts"] == 2


def test_all_keys_fail_returns_clean_503_and_nothing_saved(client, new_session, unique):
    sid = new_session()
    r = _post(client, sid, unique("hello"), "*=429")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_explicit_list_of_all_keys_fails(client, new_session, unique):
    r = _post(client, new_session(), unique("hello"), "key_1=429,key_2=500")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}


def test_503_keeps_previous_history_intact(client, new_session, unique):
    sid = new_session()
    assert _post(client, sid, unique("first")).status_code == 200
    assert _post(client, sid, unique("second"), "*=503").status_code == 503
    history = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert len(history) == 2


def test_simulation_is_per_request_only(client, new_session, unique):
    assert _post(client, new_session(), unique("a"), "key_1=429").json()["metadata"]["key_id"] == "key_2"
    nxt = _post(client, new_session(), unique("b")).json()["metadata"]
    assert nxt["key_id"] == "key_1" and nxt["fallback_attempts"] == 0


def test_simulation_bypasses_cache_so_failover_is_visible(client, new_session, unique):
    msg = unique("What is the capital of France?")
    assert _post(client, new_session(), msg).json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    r = _post(client, new_session(), msg, "key_1=429").json()["metadata"]
    assert r["resolution_source"] == "LIVE_INFERENCE" and r["key_id"] == "key_2"
    assert _post(client, new_session(), msg, "*=429").status_code == 503


def test_header_ignored_when_simulation_disabled(make_client, new_session, unique):
    c = make_client(enable_failure_simulation=False)
    r = _post(c, new_session(), unique("hello"), "*=429")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1"


def test_successful_simulated_request_is_saved(client, new_session, unique):
    sid = new_session()
    _post(client, sid, unique("hello"), "key_1=500")
    msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert msgs[1]["metadata"]["key_id"] == "key_2"
    assert msgs[1]["metadata"]["fallback_attempts"] == 1


# ---- real provider failures (no simulation) ---------------------------------

@pytest.mark.parametrize("bad_key", ["sk-429", "sk-quota", "sk-500", "sk-502", "sk-503", "sk-401", "sk-empty"])
def test_real_provider_error_on_first_key_fails_over(make_client, new_session, unique, bad_key):
    c = make_client([bad_key, "sk-ok-2"])
    r = _post(c, new_session(), unique("hello"))
    assert r.status_code == 200, r.text
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1


def test_real_failures_on_every_key_return_503(make_client, new_session, unique):
    c = make_client(["sk-429", "sk-500", "sk-quota"])
    sid = new_session()
    r = _post(c, sid, unique("hello"))
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert c.get(f"/sessions/{sid}/messages").status_code == 404


def test_unreachable_provider_returns_503(make_client, new_session, unique):
    c = make_client(llm_api_base="http://127.0.0.1:9/v1", llm_timeout_seconds=2)
    r = _post(c, new_session(), unique("hello"))
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}


def test_no_keys_configured_returns_503(make_client, new_session):
    c = make_client(keys=None, api_keys=[], models=[])
    r = _post(c, new_session(), "hello")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}


# ---- header parser ----------------------------------------------------------

def test_header_parser():
    assert parse_simulation_header("key_1=429") == {"key_1": 429}
    assert parse_simulation_header("key_1=429, key_2=500") == {"key_1": 429, "key_2": 500}
    assert parse_simulation_header("*=429") == {"*": 429}
    assert parse_simulation_header("key_1=418,bogus,key_x=500,key_2=503") == {"key_2": 503}
    assert parse_simulation_header("") == {}
    assert parse_simulation_header(None) == {}


@pytest.mark.parametrize("bad_key", ["sk-400", "sk-404"])
def test_other_provider_errors_never_crash(make_client, new_session, unique, bad_key):
    """A 4xx from one key (bad request, model not found) still fails over to the next key."""
    c = make_client([bad_key, "sk-ok-2"])
    r = _post(c, new_session(), unique("hello"))
    assert r.status_code == 200, r.text
    assert r.json()["metadata"]["key_id"] == "key_2"
