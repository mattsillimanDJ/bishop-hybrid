import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route
from app.services import memory_service
from app.services.memory_service import (
    add_memory,
    delete_memory_by_exact_content,
    get_memories,
)


client = TestClient(app)


def make_event(text: str, event_id: str = "evt-1", user_id: str = "U123", channel_id: str = "C123"):
    return {
        "type": "event_callback",
        "event_id": event_id,
        "event": {
            "type": "app_mention",
            "user": user_id,
            "channel": channel_id,
            "text": f"<@BOT> {text}",
            "ts": "123.456",
        },
    }


def reset_route_state():
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()


@pytest.fixture
def temp_memory_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(memory_service, "DB_PATH", test_db_path)


# ----------------------------
# SERVICE LAYER
# ----------------------------

def test_exact_delete_succeeds_for_owner_in_current_lane(temp_memory_db):
    add_memory("matt", "note", "dinner at 7", lane="family", visibility="private")
    add_memory("matt", "note", "buy gift for carmen", lane="family", visibility="private")

    result = delete_memory_by_exact_content(
        user_id="matt", content="dinner at 7", lane="family"
    )

    assert result["deleted"] is True
    assert result["content"] == "dinner at 7"
    assert result["lane"] == "family"
    assert result["owner_user_id"] == "matt"

    remaining = get_memories(user_id="matt", lane="family")
    contents = [m["content"] for m in remaining]
    assert "dinner at 7" not in contents
    assert "buy gift for carmen" in contents


def test_exact_delete_returns_not_found_when_only_partial_match_exists(temp_memory_db):
    add_memory("matt", "note", "dinner at 7 with parents", lane="family", visibility="private")

    result = delete_memory_by_exact_content(
        user_id="matt", content="dinner at 7", lane="family"
    )

    assert result["deleted"] is False

    remaining = get_memories(user_id="matt", lane="family")
    assert any(m["content"] == "dinner at 7 with parents" for m in remaining)


def test_exact_delete_does_not_delete_from_another_lane(temp_memory_db):
    add_memory("matt", "note", "dinner at 7", lane="family", visibility="private")
    add_memory("matt", "note", "dinner at 7", lane="work", visibility="private")

    result = delete_memory_by_exact_content(
        user_id="matt", content="dinner at 7", lane="family"
    )

    assert result["deleted"] is True
    assert result["lane"] == "family"

    work_remaining = get_memories(user_id="matt", lane="work")
    assert any(m["content"] == "dinner at 7" for m in work_remaining)

    family_remaining = get_memories(user_id="matt", lane="family")
    assert not any(m["content"] == "dinner at 7" for m in family_remaining)


def test_exact_delete_does_not_delete_another_owners_memory(temp_memory_db):
    add_memory("carmen", "note", "dinner at 7", lane="family", visibility="shared")

    result = delete_memory_by_exact_content(
        user_id="matt", content="dinner at 7", lane="family"
    )

    assert result["deleted"] is False

    carmen_remaining = get_memories(user_id="carmen", lane="family")
    assert any(m["content"] == "dinner at 7" for m in carmen_remaining)


def test_exact_delete_removes_only_most_recent_when_duplicates_exist(temp_memory_db, monkeypatch):
    # Bypass add_memory's dedupe by inserting directly with distinct ids
    memory_service.init_db()
    conn = memory_service.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_entries (user_id, owner_user_id, category, content, lane, visibility, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("matt", "matt", "note", "dinner at 7", "family", "private", "2026-01-01 10:00:00"),
    )
    cur.execute(
        """
        INSERT INTO memory_entries (user_id, owner_user_id, category, content, lane, visibility, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("matt", "matt", "note", "dinner at 7", "family", "private", "2026-02-01 10:00:00"),
    )
    conn.commit()
    conn.close()

    result = delete_memory_by_exact_content(
        user_id="matt", content="dinner at 7", lane="family"
    )

    assert result["deleted"] is True

    remaining = get_memories(user_id="matt", lane="family")
    dinner_rows = [m for m in remaining if m["content"] == "dinner at 7"]
    assert len(dinner_rows) == 1


# ----------------------------
# ROUTE LAYER
# ----------------------------

def test_slack_forget_exact_memory_route_calls_exact_delete(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_exact(*args, **kwargs):
        captured["content"] = kwargs.get("content")
        captured["lane"] = kwargs.get("lane")
        captured["user_id"] = kwargs.get("user_id")
        return {"deleted": True, "lane": "family"}

    def fail_partial_delete(*args, **kwargs):
        raise AssertionError(
            "delete_memory_by_query should not be called for 'forget exact memory ...'"
        )

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_exact_content", fake_delete_exact)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fail_partial_delete)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *a, **kw: "family")

    client.post(
        "/slack/events",
        json=make_event("forget exact memory dinner at 7", event_id="evt-exact"),
    )

    assert captured["content"] == "dinner at 7"
    assert captured["lane"] == "family"
    assert "Forgot exact memory in the family lane: dinner at 7" in captured["text"]


def test_slack_forget_exact_memory_no_match_message(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "delete_memory_by_exact_content",
        lambda **kwargs: {"deleted": False},
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *a, **kw: "family")

    client.post(
        "/slack/events",
        json=make_event("forget exact memory dinner at 7", event_id="evt-exact-miss"),
    )

    assert (
        "could not find an exact match to forget in the family lane: dinner at 7"
        in captured["text"]
    )


def test_slack_partial_forget_still_uses_partial_delete(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        captured["lane"] = kwargs.get("lane")
        return {"deleted": True, "lane": "family"}

    def fail_exact_delete(*args, **kwargs):
        raise AssertionError(
            "delete_memory_by_exact_content should not be called for plain 'forget ...'"
        )

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "delete_memory_by_exact_content", fail_exact_delete)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *a, **kw: "family")

    client.post(
        "/slack/events",
        json=make_event("forget dinner at 7", event_id="evt-partial-pres"),
    )

    assert captured["query"] == "dinner at 7"
    assert captured["lane"] == "family"
    assert "Forgot memory in the family lane matching: dinner at 7" in captured["text"]
