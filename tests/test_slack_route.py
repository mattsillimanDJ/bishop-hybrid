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
        },
    }


def test_url_verification():
    response = client.post(
        "/slack/events",
        json={"type": "url_verification", "challenge": "abc123"},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_ignores_non_event_callback():
    response = client.post("/slack/events", json={"type": "something_else"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_ignores_non_app_mention():
    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event_id": "evt-non-mention",
            "event": {"type": "message", "user": "U123", "channel": "C123", "text": "hello"},
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_ignores_bot_messages():
    response = client.post(
        "/slack/events",
        json={
            "type": "event_callback",
            "event_id": "evt-bot",
            "event": {
                "type": "app_mention",
                "bot_id": "B999",
                "user": "U123",
                "channel": "C123",
                "text": "<@BOT> hello",
            },
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_skips_retry_header():
    response = client.post(
        "/slack/events",
        headers={"x-slack-retry-num": "1"},
        json=make_event("hello", event_id="evt-retry"),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_skips_duplicate_event_id(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    post_calls = []

    def fake_post_message(channel, text):
        post_calls.append((channel, text))
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    first = client.post("/slack/events", json=make_event("hello", event_id="evt-dup"))
    second = client.post("/slack/events", json=make_event("hello again", event_id="evt-dup"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True}
    assert len(post_calls) == 1


def test_skips_near_duplicate_message_same_text(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    post_calls = []

    def fake_post_message(channel, text):
        post_calls.append((channel, text))
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    first = client.post("/slack/events", json=make_event("yes please", event_id="evt-a"))
    second = client.post("/slack/events", json=make_event("yes please", event_id="evt-b"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True}
    assert len(post_calls) == 1


def test_skips_near_duplicate_message_ignores_trailing_punctuation(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    post_calls = []

    def fake_post_message(channel, text):
        post_calls.append((channel, text))
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    first = client.post("/slack/events", json=make_event("yes please", event_id="evt-c"))
    second = client.post("/slack/events", json=make_event("yes please!", event_id="evt-d"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True}
    assert len(post_calls) == 1


def test_help_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("help", event_id="evt-help"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["channel"] == "C123"
    assert "Here are the commands I understand:" in captured["text"]
    assert "show recent conversations" in captured["text"]
    assert "show last 5 conversations" in captured["text"]


def test_show_provider_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_provider_override", lambda: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show provider", event_id="evt-provider"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "Effective provider: openai" in captured["text"]
    assert "Override: none" in captured["text"]


def test_status_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_provider_override", lambda: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("status", event_id="evt-status"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "*Bishop Status*" in captured["text"]
    assert "*Mode:* default" in captured["text"]
    assert "*Effective provider:* openai" in captured["text"]


def test_provider_openai_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    provider_calls = []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_provider_override", lambda provider: provider_calls.append(provider))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("provider openai", event_id="evt-provider-openai"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert provider_calls == ["openai"]
    assert captured["text"] == "Provider override set to openai."


def test_provider_default_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    cleared = {"called": False}

    def fake_clear_provider_override():
        cleared["called"] = True

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_provider_override", fake_clear_provider_override)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("provider default", event_id="evt-provider-default"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert cleared["called"] is True
    assert captured["text"] == "Provider override cleared. Falling back to Railway default."


def test_mode_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    mode_calls = []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", lambda user_id, mode: mode_calls.append((user_id, mode)))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("mode work", event_id="evt-mode"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert mode_calls == [("U123", "work")]
    assert captured["text"] == "Mode set to work."


def test_show_mode_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "personal")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show mode", event_id="evt-show-mode"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["text"] == "Current mode: personal"


def test_show_recent_conversations_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    received = {}

    def fake_get_recent_conversations_for_user(
        user_id,
        limit,
        platform,
        exclude_utility_commands,
        fetch_limit,
    ):
        received["user_id"] = user_id
        received["limit"] = limit
        received["platform"] = platform
        received["exclude_utility_commands"] = exclude_utility_commands
        received["fetch_limit"] = fetch_limit
        return [
            {
                "created_at": "2026-04-02T14:30:00+00:00",
                "user_message": "tell me about the vendor plan",
                "assistant_response": "Here is the vendor plan summary",
            },
            {
                "created_at": "2026-04-02T14:25:00+00:00",
                "user_message": "mode work",
                "assistant_response": "Mode set to work.",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_recent_conversations_for_user",
        fake_get_recent_conversations_for_user,
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("show recent conversations", event_id="evt-show-recent"),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert received == {
        "user_id": "U123",
        "limit": 5,
        "platform": "slack",
        "exclude_utility_commands": True,
        "fetch_limit": 50,
    }
    assert "Here are your recent conversations:" in captured["text"]
    assert "You: tell me about the vendor plan" in captured["text"]
    assert "Bishop: Here is the vendor plan summary" in captured["text"]


def test_show_last_5_conversations_command(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    received = {}

    def fake_get_recent_conversations_for_user(
        user_id,
        limit,
        platform,
        exclude_utility_commands,
        fetch_limit,
    ):
        received["user_id"] = user_id
        received["limit"] = limit
        received["platform"] = platform
        received["exclude_utility_commands"] = exclude_utility_commands
        received["fetch_limit"] = fetch_limit
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_recent_conversations_for_user",
        fake_get_recent_conversations_for_user,
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("show last 5 conversations", event_id="evt-show-last-5"),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert received == {
        "user_id": "U123",
        "limit": 5,
        "platform": "slack",
        "exclude_utility_commands": True,
        "fetch_limit": 50,
    }
    assert captured["text"] == "I don’t have any recent conversations for you yet."


def test_show_last_conversations_caps_at_10(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    received = {}

    def fake_get_recent_conversations_for_user(
        user_id,
        limit,
        platform,
        exclude_utility_commands,
        fetch_limit,
    ):
        received["limit"] = limit
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_recent_conversations_for_user",
        fake_get_recent_conversations_for_user,
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("show last 99 conversations", event_id="evt-show-last-99"),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert received["limit"] == 10
    assert captured["text"] == "I don’t have any recent conversations for you yet."


def test_normal_chat_message(monkeypatch):
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()

    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("hello bishop", event_id="evt-chat"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["text"] == "Hello back"
