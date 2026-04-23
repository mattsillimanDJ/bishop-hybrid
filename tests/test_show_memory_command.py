from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route


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


def test_show_memory_returns_all_lane_memories(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_memories(*args, **kwargs):
        return [
            {
                "content": "dinner at 7",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            },
            {
                "content": "buy gift",
                "lane": "family",
                "visibility": "private",
                "owner_user_id": "carmen",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt" if user_id == "matt" else "Carmen",
    )

    response = client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-show-memory"),
    )

    assert response.status_code == 200
    assert "Here is what I remember in the family lane:" in captured["text"]
    assert "* Matt shared in family: dinner at 7" in captured["text"]
    assert "* Carmen private in family: buy gift" in captured["text"]


def test_what_do_you_remember_returns_lane_memory(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_memories(*args, **kwargs):
        return [
            {
                "content": "dinner at 7",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            }
        ]

    def fail_generate_reply(*args, **kwargs):
        raise AssertionError("generate_reply should not be called for 'what do you remember'")

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = client.post(
        "/slack/events",
        json=make_event("what do you remember", event_id="evt-what-do-you-remember"),
    )

    assert response.status_code == 200
    assert "Here is what I remember in the family lane:" in captured["text"]
    assert "* Matt shared in family: dinner at 7" in captured["text"]


def test_what_do_you_remember_with_trailing_question_mark_matches(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_memories(*args, **kwargs):
        return [
            {
                "content": "dinner at 7",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            }
        ]

    def fail_generate_reply(*args, **kwargs):
        raise AssertionError(
            "generate_reply should not be called for 'what do you remember?'"
        )

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = client.post(
        "/slack/events",
        json=make_event("what do you remember?", event_id="evt-wdyr-q"),
    )

    assert response.status_code == 200
    assert "Here is what I remember in the family lane:" in captured["text"]


def test_what_do_you_remember_in_full_with_trailing_question_mark_matches(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_build(user_id, lane, include_boilerplate=False):
        captured["include_boilerplate"] = include_boilerplate
        return "stubbed full memory response"

    def fail_generate_reply(*args, **kwargs):
        raise AssertionError(
            "generate_reply should not be called for 'what do you remember in full?'"
        )

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "build_lane_memory_response", fake_build)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    response = client.post(
        "/slack/events",
        json=make_event("what do you remember in full?", event_id="evt-wdyr-full-q"),
    )

    assert response.status_code == 200
    assert captured["include_boilerplate"] is True
    assert captured["text"] == "stubbed full memory response"


def test_show_memory_handles_empty(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    response = client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-show-memory-empty"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I do not have any saved memory yet in the family lane."

