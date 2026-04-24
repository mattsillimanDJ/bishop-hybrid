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


def _stub_common(monkeypatch, lane: str = "matt"):
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: lane,
    )
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda l: "private")


def test_attention_command_routes_and_includes_tasks_and_memory(monkeypatch):
    reset_route_state()
    captured = {}
    task_calls = []
    memory_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="matt")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)

    def fake_get_tasks(user_id, lane=None, status="pending", limit=10):
        task_calls.append({"user_id": user_id, "lane": lane, "status": status})
        return [
            {
                "created_at": "2026-04-24T09:00:00+00:00",
                "task_text": "finish the attention command",
                "assistant_commitment": "On it.",
            },
            {
                "created_at": "2026-04-24T10:00:00+00:00",
                "task_text": "run the tests",
                "assistant_commitment": "",
            },
        ]

    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)

    def fake_get_memories(user_id, lane=None, limit=20):
        memory_calls.append(lane)
        return [
            {
                "id": 1,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "ship the attention dashboard",
            },
            {
                "id": 2,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "check PR #42",
            },
        ]

    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention", event_id="evt-attention-1"),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert text.startswith("What needs your attention in the matt lane:")
    assert "Pending tasks:" in text
    assert "finish the attention command" in text
    assert "run the tests" in text
    assert "Working memory:" in text
    assert "ship the attention dashboard" in text
    assert "check PR #42" in text

    assert task_calls == [{"user_id": "U123", "lane": "matt", "status": "pending"}]
    assert memory_calls == ["matt"]


def test_attention_command_tolerates_trailing_question_mark(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="work")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, lane=None, status="pending", limit=10: [],
    )
    monkeypatch.setattr(
        slack_route, "get_memories", lambda user_id, lane=None, limit=20: []
    )

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention?", event_id="evt-attention-2"),
    )

    assert response.status_code == 200
    assert (
        captured["text"]
        == "You're clear in the work lane. No pending tasks or working memory items."
    )


def test_attention_command_empty_state_is_clean(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="matt")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, lane=None, status="pending", limit=10: [],
    )
    monkeypatch.setattr(
        slack_route, "get_memories", lambda user_id, lane=None, limit=20: []
    )

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention", event_id="evt-attention-empty"),
    )

    assert response.status_code == 200
    assert (
        captured["text"]
        == "You're clear in the matt lane. No pending tasks or working memory items."
    )


def test_attention_command_omits_memory_section_when_only_tasks(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="matt")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, lane=None, status="pending", limit=10: [
            {
                "created_at": "2026-04-24T09:00:00+00:00",
                "task_text": "only task",
                "assistant_commitment": "",
            }
        ],
    )
    monkeypatch.setattr(
        slack_route, "get_memories", lambda user_id, lane=None, limit=20: []
    )

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention", event_id="evt-attention-only-tasks"),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert "What needs your attention in the matt lane:" in text
    assert "Pending tasks:" in text
    assert "only task" in text
    assert "Working memory:" not in text


def test_attention_command_omits_task_section_when_only_memory(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="matt")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, lane=None, status="pending", limit=10: [],
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
                "content": "lone working memory item",
            }
        ],
    )

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention", event_id="evt-attention-only-memory"),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert "What needs your attention in the matt lane:" in text
    assert "Working memory:" in text
    assert "lone working memory item" in text
    assert "Pending tasks:" not in text


def test_attention_command_is_lane_scoped(monkeypatch):
    reset_route_state()
    captured = {}
    task_calls = []
    memory_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    _stub_common(monkeypatch, lane="dj")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)

    def fake_get_tasks(user_id, lane=None, status="pending", limit=10):
        task_calls.append(lane)
        return []

    def fake_get_memories(user_id, lane=None, limit=20):
        memory_calls.append(lane)
        return []

    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)

    response = client.post(
        "/slack/events",
        json=make_event("what needs my attention", event_id="evt-attention-lane"),
    )

    assert response.status_code == 200
    assert task_calls == ["dj"]
    assert memory_calls == ["dj"]
    assert "in the dj lane" in captured["text"]
