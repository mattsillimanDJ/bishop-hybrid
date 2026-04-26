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

    assert text.startswith("Here’s what needs your attention in the matt lane:")
    assert "Pending tasks\n" in text
    assert "Pending tasks:" not in text
    assert "• finish the attention command" in text
    assert "• run the tests" in text
    assert "Commitment:" not in text
    assert "2026-04-24" not in text
    assert "Operational context\n" in text
    assert "Operational context:" not in text
    assert "Working memory:" not in text
    assert "• ship the attention dashboard" in text
    assert "• check PR #42" in text

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
    assert captured["text"] == (
        "Nothing urgent in the work lane right now.\n\n"
        "I have background context saved, but nothing that needs action."
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
    assert captured["text"] == (
        "Nothing urgent in the matt lane right now.\n\n"
        "I have background context saved, but nothing that needs action."
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

    assert "Here’s what needs your attention in the matt lane:" in text
    assert "Pending tasks\n" in text
    assert "Pending tasks:" not in text
    assert "• only task" in text
    assert "Commitment:" not in text
    assert "2026-04-24" not in text
    assert "Working memory:" not in text
    assert "Operational context" not in text


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

    assert "Here’s what needs your attention in the matt lane:" in text
    assert "Operational context\n" in text
    assert "Operational context:" not in text
    assert "Working memory:" not in text
    assert "• lone working memory item" in text
    assert "Pending tasks" not in text


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


def test_attention_pending_tasks_render_as_plain_bullets(monkeypatch):
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, lane=None, status="pending", limit=10: [
            {
                "created_at": "2026-04-24T09:00:00+00:00",
                "task_text": "follow up on Bishop attention dashboard",
                "assistant_commitment": "On it.",
            }
        ],
    )
    monkeypatch.setattr(
        slack_route, "get_memories", lambda user_id, lane=None, limit=20: []
    )

    response = slack_route.build_attention_response(user_id="matt", lane="matt")

    assert response == (
        "Here’s what needs your attention in the matt lane:\n"
        "\n"
        "Pending tasks\n"
        "• follow up on Bishop attention dashboard"
    )


def test_attention_does_not_show_durable_preference_as_urgent(monkeypatch):
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
                "task_text": "draft the launch note",
                "assistant_commitment": "",
            }
        ],
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
                "category": "preference",
                "content": "Matt wants Bishop to feel friendly and concise.",
            },
            {
                "id": 2,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "note",
                "content": "follow up on the Bishop attention dashboard",
            },
        ],
    )

    response = client.post(
        "/slack/events",
        json=make_event(
            "what needs my attention", event_id="evt-attention-durable-pref"
        ),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert "Pending tasks\n" in text
    assert "Pending tasks:" not in text
    assert "• draft the launch note" in text
    assert "Operational context\n" in text
    assert "Operational context:" not in text
    assert "• follow up on the Bishop attention dashboard" in text
    assert "Matt wants Bishop to feel friendly and concise" not in text


def test_attention_acknowledges_durable_when_no_actionables(monkeypatch):
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
                "category": "preference",
                "content": (
                    "Matt wants Bishop to feel like a personal AI operating system, "
                    "not a generic chatbot."
                ),
            },
            {
                "id": 2,
                "owner_user_id": user_id,
                "lane": lane,
                "visibility": "private",
                "category": "profile",
                "content": "Matt's blood type is O+.",
            },
        ],
    )

    response = client.post(
        "/slack/events",
        json=make_event(
            "what needs my attention", event_id="evt-attention-only-durable"
        ),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert text == (
        "Nothing urgent in the matt lane right now.\n\n"
        "I have background context saved, but nothing that needs action."
    )
    assert "Pending tasks" not in text
    assert "Operational context" not in text
    assert "Matt's blood type" not in text
    assert "personal AI operating system" not in text


def test_attention_demotes_note_content_that_reads_as_durable(monkeypatch):
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
                "content": "Matt wants Bishop to feel like a personal AI operating system.",
            },
        ],
    )

    response = client.post(
        "/slack/events",
        json=make_event(
            "what needs my attention", event_id="evt-attention-durable-note"
        ),
    )

    assert response.status_code == 200
    text = captured["text"]

    assert text == (
        "Nothing urgent in the matt lane right now.\n\n"
        "I have background context saved, but nothing that needs action."
    )
    assert "Operational context" not in text
    assert "personal AI operating system" not in text


def test_is_attention_actionable_filters_durable_categories():
    assert not slack_route.is_attention_actionable(
        {"category": "preference", "content": "Working on the Bishop project."}
    )
    assert not slack_route.is_attention_actionable(
        {"category": "profile", "content": "Bishop is a private AI workspace."}
    )
    assert not slack_route.is_attention_actionable(
        {
            "category": "note",
            "content": (
                "Matt wants Bishop to feel like a personal AI operating system, "
                "not a generic chatbot."
            ),
        }
    )
    assert slack_route.is_attention_actionable(
        {"category": "note", "content": "ship the attention dashboard"}
    )
    assert slack_route.is_attention_actionable(
        {"category": "note", "content": "check PR #42"}
    )
