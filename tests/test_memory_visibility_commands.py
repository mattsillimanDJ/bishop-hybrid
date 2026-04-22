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


def test_remember_shared_sets_visibility_shared(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember shared dinner at 7", event_id="evt-shared"),
    )

    assert response.status_code == 200
    assert captured["visibility"] == "shared"
    assert captured["content"] == "dinner at 7"


def test_remember_private_sets_visibility_private(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember private keep this secret", event_id="evt-private"),
    )

    assert response.status_code == 200
    assert captured["visibility"] == "private"
    assert captured["content"] == "keep this secret"


def test_default_remember_uses_lane_default_visibility(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "shared",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember dinner plans", event_id="evt-default"),
    )

    assert response.status_code == 200
    assert captured["visibility"] == "shared"
    assert captured["content"] == "dinner plans"


def test_remember_shared_overrides_lane_default(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "private",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember shared team dinner", event_id="evt-override-shared"),
    )

    assert response.status_code == 200
    assert captured["visibility"] == "shared"
    assert captured["content"] == "team dinner"


def test_remember_this_colon_strips_prefix(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "shared",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember this: dinner at 7", event_id="evt-remember-this-colon"),
    )

    assert response.status_code == 200
    assert captured["content"] == "dinner at 7"
    assert captured["visibility"] == "shared"


def test_remember_private_overrides_lane_default(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_add_memory(*args, **kwargs):
        captured["visibility"] = kwargs.get("visibility")
        captured["content"] = kwargs.get("content")

    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "family",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "shared",
    )

    response = client.post(
        "/slack/events",
        json=make_event("remember private keep this quiet", event_id="evt-override-private"),
    )

    assert response.status_code == 200
    assert captured["visibility"] == "private"
    assert captured["content"] == "keep this quiet"
