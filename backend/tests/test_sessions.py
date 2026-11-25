"""Multi-turn state, session isolation, history endpoint and SQLite persistence."""

from __future__ import annotations

import sqlite3

from app.config import sqlite_path_from_url


def _chat(client, sid, message, **extra):
    r = client.post("/chat", json={"session_id": sid, "message": message, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_bot_remembers_earlier_messages(client, new_session, provider):
    sid = new_session()
    _chat(client, sid, "My name is Aaryan")
    reply = _chat(client, sid, "What is my name?")["reply"]
    # the fake provider echoes the previous user turn it received -> history was sent
    assert "earlier: My name is Aaryan" in reply
    sent = provider.requests[-1]["body"]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]


def test_client_sends_only_new_message_and_backend_builds_history(client, new_session, provider):
    sid = new_session()
    for i in range(3):
        _chat(client, sid, f"turn {i}")
    sent = provider.requests[-1]["body"]["messages"]
    assert len(sent) == 1 + 2 * 2 + 1  # system + 2 previous exchanges + new message


def test_sessions_are_isolated(client, new_session):
    a, b = new_session(), new_session()
    _chat(client, a, "secret word is banana")
    reply_b = _chat(client, b, "what is the secret word?")["reply"]
    assert "banana" not in reply_b
    assert "earlier: nothing" in reply_b


def test_history_endpoint(client, new_session):
    sid = new_session()
    first = _chat(client, sid, "What is the capital of France?")
    _chat(client, sid, "And of Italy?")
    r = client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    msgs = body["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]  # oldest first
    assert msgs[0]["content"] == "What is the capital of France?"
    assert msgs[1]["content"] == first["reply"]
    assert all(m["role"] != "system" for m in msgs)  # no system prompt
    assert "metadata" not in msgs[0]  # metadata on assistant messages only
    meta = msgs[1]["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["input_tokens"] == first["metadata"]["input_tokens"]
    assert meta["output_tokens"] == first["metadata"]["output_tokens"]
    assert all("created_at" in m for m in msgs)


def test_unknown_session_404(client):
    r = client.get("/sessions/s-does-not-exist/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_message_is_stored_trimmed(client, new_session):
    sid = new_session()
    _chat(client, sid, "   padded message \n")
    assert client.get(f"/sessions/{sid}/messages").json()["messages"][0]["content"] == "padded message"


def test_system_prompt_override_is_sent_and_remembered(client, new_session, provider):
    sid = new_session()
    _chat(client, sid, "hi", system_prompt="You are a pirate.")
    assert provider.requests[-1]["body"]["messages"][0] == {"role": "system", "content": "You are a pirate."}
    _chat(client, sid, "hi again")  # no system_prompt sent -> session keeps its override
    assert provider.requests[-1]["body"]["messages"][0]["content"] == "You are a pirate."
    # another session still uses the default prompt
    _chat(client, new_session(), "hello")
    assert provider.requests[-1]["body"]["messages"][0]["content"] != "You are a pirate."


def test_history_survives_restart(make_client, new_session, tmp_path):
    sid = new_session()
    c1 = make_client()
    _chat(c1, sid, "remember me")
    c1.__exit__(None, None, None)

    c2 = make_client()  # same database file, brand-new app instance
    msgs = c2.get(f"/sessions/{sid}/messages").json()["messages"]
    assert msgs[0]["content"] == "remember me"
    reply = _chat(c2, sid, "do you remember?")["reply"]
    assert "earlier: remember me" in reply


def test_schema_matches_assignment(client, tmp_path):
    conn = sqlite3.connect(tmp_path / "app.db")
    cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(messages)")}
    assert cols == {
        "id": "INTEGER", "session_id": "TEXT", "role": "TEXT",
        "content": "TEXT", "metadata": "TEXT", "created_at": "TEXT",
    }


def test_database_url_parsing():
    assert sqlite_path_from_url("sqlite:////data/app.db") == "/data/app.db"
    assert sqlite_path_from_url("sqlite:///./app.db") == "./app.db"
    assert sqlite_path_from_url("/tmp/x.db") == "/tmp/x.db"
