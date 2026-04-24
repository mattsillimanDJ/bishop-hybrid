import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route
from app.services import memory_service
from app.services.memory_service import (
    _is_basic_identity_clutter,
    add_memory,
    get_memories,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def use_temp_memory_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(memory_service, "DB_PATH", test_db_path)


def make_event(text: str, event_id: str, user_id: str = "U123", channel_id: str = "C123"):
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


@pytest.mark.parametrize(
    "phrase",
    [
        "User's name is Matt.",
        "My name is Matt.",
        "The user's name is Matt.",
        "Matt is the user.",
        "User is Matt.",
        "  my name is matt  ",
        "MY NAME IS MATT",
        "my name is matt!",
        "The users name is Matt",
    ],
)
def test_identity_clutter_is_detected(phrase):
    assert _is_basic_identity_clutter(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "Matt is an advertising executive and DJ.",
        "Matt is building Bishop as a personal operating system.",
        "Matt prefers terminal-first instructions.",
        "Matt wants Bishop to feel like a personal AI operating system.",
        "Matt lives in Brooklyn.",
        "dinner at 7",
        "",
        "   ",
    ],
)
def test_non_clutter_is_not_detected(phrase):
    assert _is_basic_identity_clutter(phrase) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "User's name is Matt.",
        "My name is Matt.",
        "The user's name is Matt.",
        "Matt is the user.",
        "User is Matt.",
    ],
)
def test_add_memory_skips_basic_identity_clutter(phrase):
    result = add_memory(
        user_id="matt",
        category="note",
        content=phrase,
        lane="matt",
        visibility="private",
    )

    assert result.get("skipped") is True
    assert result.get("reason") == "basic_identity"
    assert "id" not in result

    assert get_memories(user_id="matt", lane="matt") == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Matt is an advertising executive and DJ.",
        "Matt is building Bishop as a personal operating system.",
        "Matt prefers terminal-first instructions.",
        "Matt wants Bishop to feel like a personal AI operating system.",
    ],
)
def test_add_memory_still_saves_useful_profile_and_preferences(phrase):
    result = add_memory(
        user_id="matt",
        category="note",
        content=phrase,
        lane="matt",
        visibility="private",
    )

    assert result.get("skipped") is not True
    assert isinstance(result.get("id"), int)
    assert result["content"] == phrase

    stored = get_memories(user_id="matt", lane="matt")
    assert any(row["content"] == phrase for row in stored)


def test_slack_remember_clutter_returns_graceful_response(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "private")
    monkeypatch.setattr(
        slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "matt"
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember my name is Matt", event_id="evt-clutter-1"),
    )

    assert response.status_code == 200
    assert (
        captured["text"]
        == "I already know that basic identity detail, so I won't add it again."
    )

    assert get_memories(user_id="U123", lane="matt") == []


def test_slack_remember_useful_profile_still_saves(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "private")
    monkeypatch.setattr(
        slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "matt"
    )

    response = client.post(
        "/slack/events",
        json=make_event(
            "remember that Matt is an advertising executive and DJ",
            event_id="evt-useful-1",
        ),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("Got it. I'll remember this in the matt lane:")

    stored = get_memories(user_id="U123", lane="matt")
    assert any(
        row["content"] == "Matt is an advertising executive and DJ" for row in stored
    )
