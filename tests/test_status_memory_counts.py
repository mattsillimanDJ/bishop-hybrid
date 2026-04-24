from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route


client = TestClient(app)


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


def reset_route_state():
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()


def _stub_provider_env(monkeypatch):
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_provider_override", lambda: None)
    monkeypatch.setattr(
        slack_route,
        "get_provider_resolution",
        lambda: {
            "override": None,
            "override_ok": False,
            "override_message": "No override set",
            "default_provider": "openai",
            "default_ok": True,
            "default_message": "OpenAI configuration looks valid",
            "effective_provider": "openai",
            "effective_from": "default",
        },
    )
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "validate_provider_config", lambda provider: (True, "ok"))
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work"
    )


def test_status_output_includes_existing_fields_and_memory_counts(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_provider_env(monkeypatch)
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)

    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [{"task_text": "a"}, {"task_text": "b"}],
    )

    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane=None, limit=20: [
            {
                "id": 1,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "dinner at 7 tonight",
            },
            {
                "id": 2,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "call the plumber tomorrow",
            },
            {
                "id": 3,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "profile",
                "content": "Matt lives in Brooklyn",
            },
        ],
    )

    response = client.post("/slack/events", json=make_event("status", event_id="evt-status-counts"))

    assert response.status_code == 200
    text = captured["text"]

    assert "*Bishop Status*" in text
    assert "*Lane:* work" in text
    assert "*Mode:* default" in text
    assert "*Effective provider:* openai" in text
    assert "*Active model:* gpt-4.1-mini" in text
    assert "*Pending tasks:* 2" in text
    assert "*Provider checks:*" in text
    assert "* OpenAI:" in text
    assert "* Claude:" in text

    assert "*Working memory:* 2" in text
    assert "*Background profile:* 1" in text


def test_status_output_shows_zero_when_memory_empty(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_provider_env(monkeypatch)
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [],
    )
    monkeypatch.setattr(
        slack_route, "get_memories", lambda user_id, lane=None, limit=20: []
    )

    response = client.post("/slack/events", json=make_event("status", event_id="evt-status-empty"))

    assert response.status_code == 200
    text = captured["text"]

    assert "*Pending tasks:* 0" in text
    assert "*Working memory:* 0" in text
    assert "*Background profile:* 0" in text


def test_status_output_counts_only_current_lane(monkeypatch):
    reset_route_state()
    captured = {}
    lane_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_provider_env(monkeypatch)
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [],
    )

    def fake_get_memories(user_id, lane=None, limit=20):
        lane_calls.append(lane)
        return [
            {
                "id": 10,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "dinner at 7 tonight",
            }
        ]

    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)

    response = client.post(
        "/slack/events", json=make_event("status", event_id="evt-status-lane-scope")
    )

    assert response.status_code == 200
    assert lane_calls == ["work"]
    assert "*Working memory:* 1" in captured["text"]
    assert "*Background profile:* 0" in captured["text"]
