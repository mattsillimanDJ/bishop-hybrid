from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route

client = TestClient(app)


def make_payload(text, event_id="evt-1", user_id="U123", channel_id="C123"):
    return {
        "type": "event_callback",
        "event_id": event_id,
        "event": {
            "type": "app_mention",
            "user": user_id,
            "channel": channel_id,
            "text": f"<@BISHOP> {text}",
        },
    }


def test_slack_url_verification():
    response = client.post(
        "/slack/events",
        json={"type": "url_verification", "challenge": "hello123"},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "hello123"}


def test_slack_status_command(monkeypatch):
    messages = []

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(slack_route, "get_provider_override", lambda: "claude")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "claude")
    monkeypatch.setattr(slack_route.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(slack_route.settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(slack_route.settings, "ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setattr(slack_route.settings, "OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setattr(slack_route.settings, "ANTHROPIC_MODEL", "claude-sonnet-4-6")

    response = client.post("/slack/events", json=make_payload("status", event_id="evt-status"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(messages) == 1
    assert messages[0][0] == "C123"
    assert "Bishop Status" in messages[0][1]
    assert "Mode:* work" in messages[0][1]
    assert "Effective provider:* claude" in messages[0][1]
    assert "Railway default provider:* openai" in messages[0][1]


def test_slack_show_provider_command(monkeypatch):
    messages = []

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_provider_override", lambda: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route.settings, "LLM_PROVIDER", "openai")

    response = client.post("/slack/events", json=make_payload("show provider", event_id="evt-provider"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(messages) == 1
    assert "Effective provider: openai" in messages[0][1]
    assert "Override: none" in messages[0][1]
    assert "Railway default: openai" in messages[0][1]


def test_slack_mode_command(monkeypatch):
    messages = []
    captured = {}

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "set_mode", lambda user_id, mode: captured.update({"user_id": user_id, "mode": mode}))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: captured.get("mode", "default"))

    response = client.post("/slack/events", json=make_payload("mode work", event_id="evt-mode"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["user_id"] == "U123"
    assert captured["mode"] == "work"
    assert len(messages) == 1
    assert messages[0][1] == "Mode set to work."


def test_slack_provider_claude_command(monkeypatch):
    messages = []
    captured = {}

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(slack_route, "set_provider_override", lambda provider: captured.update({"provider": provider}))

    response = client.post("/slack/events", json=make_payload("provider claude", event_id="evt-claude"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["provider"] == "claude"
    assert len(messages) == 1
    assert messages[0][1] == "Provider override set to claude."


def test_slack_provider_default_command(monkeypatch):
    messages = []
    captured = {"cleared": False}

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(slack_route, "clear_provider_override", lambda: captured.update({"cleared": True}))

    response = client.post("/slack/events", json=make_payload("provider default", event_id="evt-default"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["cleared"] is True
    assert len(messages) == 1
    assert "Provider override cleared" in messages[0][1]


def test_slack_normal_chat_uses_generate_reply(monkeypatch):
    messages = []

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Test normal reply")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route.settings, "OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setattr(slack_route.settings, "ANTHROPIC_MODEL", "claude-sonnet-4-6")

    response = client.post("/slack/events", json=make_payload("hello bishop", event_id="evt-chat"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(messages) == 1
    assert messages[0][1] == "Test normal reply"


def test_slack_duplicate_event_is_ignored(monkeypatch):
    messages = []

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: messages.append((channel, text)) or {"ok": True})
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Should only send once")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route.settings, "OPENAI_MODEL", "gpt-5.4")

    payload = make_payload("hello again", event_id="evt-duplicate")

    first = client.post("/slack/events", json=payload)
    second = client.post("/slack/events", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True}
    assert len(messages) == 1
