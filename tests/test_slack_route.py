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
            "event": {
                "type": "message",
                "user": "U123",
                "channel": "C123",
                "text": "hello",
            },
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
    reset_route_state()
    post_calls = []

    def fake_post_message(channel, text):
        post_calls.append((channel, text))
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    first = client.post("/slack/events", json=make_event("hello", event_id="evt-dup"))
    second = client.post("/slack/events", json=make_event("hello again", event_id="evt-dup"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(post_calls) == 1


def test_skips_near_duplicate_message_same_text(monkeypatch):
    reset_route_state()
    post_calls = []

    def fake_post_message(channel, text):
        post_calls.append((channel, text))
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Hello back")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    first = client.post("/slack/events", json=make_event("yes please", event_id="evt-a"))
    second = client.post("/slack/events", json=make_event("yes please", event_id="evt-b"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(post_calls) == 1


def test_expands_short_followup_when_previous_reply_invited_it(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Here are 3 more jokes."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_recent_conversations_for_user",
        lambda **kwargs: [
            {
                "user_message": "tell me a joke about ad agencies",
                "assistant_response": "Sure. Want 3 more?",
            }
        ],
    )

    response = client.post("/slack/events", json=make_event("yes please", event_id="evt-followup-1"))

    assert response.status_code == 200
    assert "You are continuing a Slack conversation." in captured["message_to_model"]
    assert captured["text"] == "Here are 3 more jokes."


def test_help_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("help", event_id="evt-help"))

    assert response.status_code == 200
    assert "show lane" in captured["text"]
    assert "what lane am i in" in captured["text"]
    assert "show tasks" in captured["text"]
    assert "show done" in captured["text"]
    assert "show completed" in captured["text"]
    assert "show all" in captured["text"]
    assert "show all tasks" in captured["text"]
    assert "clear done" in captured["text"]
    assert "clear completed" in captured["text"]
    assert "remove done task" in captured["text"]
    assert "remove completed task" in captured["text"]
    assert "add task" in captured["text"]
    assert "remind me" in captured["text"]


def test_show_lane_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "dj",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "private",
    )

    response = client.post("/slack/events", json=make_event("show lane", event_id="evt-show-lane"))

    assert response.status_code == 200
    assert "Current lane: dj" in captured["text"]
    assert "Channel ID: C123" in captured["text"]
    assert "Default visibility: private" in captured["text"]


def test_what_lane_am_i_in_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "work",
    )
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "shared",
    )

    response = client.post(
        "/slack/events",
        json=make_event("what lane am i in", event_id="evt-what-lane"),
    )

    assert response.status_code == 200
    assert "Current lane: work" in captured["text"]
    assert "Channel ID: C123" in captured["text"]
    assert "Default visibility: shared" in captured["text"]


def test_provider_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
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
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("provider", event_id="evt-provider"))

    assert response.status_code == 200
    assert "Effective provider: openai" in captured["text"]
    assert "Active model: gpt-4.1-mini" in captured["text"]


def test_status_command_includes_pending_tasks(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
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
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [{"task_text": "Do the thing"}],
    )
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: "work",
    )

    response = client.post("/slack/events", json=make_event("status", event_id="evt-status"))

    assert response.status_code == 200
    assert "*Lane:* work" in captured["text"]
    assert "*Pending tasks:* 1" in captured["text"]


def test_show_pending_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [
            {
                "created_at": "2026-04-03T20:00:00+00:00",
                "task_text": "Do 1, 2, and 3",
                "assistant_commitment": "On it. I'll proceed with 1, 2, and 3.",
            }
        ] if status == "pending" else [],
    )
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show pending", event_id="evt-show-pending"))

    assert response.status_code == 200
    assert "Pending tasks:" in captured["text"]
    assert "Do 1, 2, and 3" in captured["text"]


def test_show_completed_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="done", limit=10: [
            {
                "created_at": "2026-04-03T20:00:00+00:00",
                "task_text": "send the invoice",
                "assistant_commitment": "Saved as a pending task.",
            }
        ] if status == "done" else [],
    )
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show completed", event_id="evt-show-completed"))

    assert response.status_code == 200
    assert "Completed tasks:" in captured["text"]
    assert "send the invoice" in captured["text"]


def test_show_done_command_uses_done_status(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_tasks(user_id, status="pending", limit=10):
        captured["calls"].append((user_id, status, limit))
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show done", event_id="evt-show-done"))

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "done", 10)]
    assert captured["text"] == "No completed tasks right now."


def test_show_all_tasks_command(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_tasks(user_id, status="pending", limit=10):
        captured["calls"].append((user_id, status, limit))
        if status == "pending":
            return [
                {
                    "created_at": "2026-04-03T20:00:00+00:00",
                    "task_text": "review the deck",
                    "assistant_commitment": "Saved as a pending task.",
                }
            ]
        if status == "done":
            return [
                {
                    "created_at": "2026-04-03T21:00:00+00:00",
                    "task_text": "send the invoice",
                    "assistant_commitment": "Saved as a pending task.",
                }
            ]
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show all tasks", event_id="evt-show-all-tasks"))

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "pending", 10), ("U123", "done", 10)]
    assert "Pending tasks:" in captured["text"]
    assert "review the deck" in captured["text"]
    assert "Completed tasks:" in captured["text"]
    assert "send the invoice" in captured["text"]


def test_show_all_command_when_no_tasks(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_tasks(user_id, status="pending", limit=10):
        captured["calls"].append((user_id, status, limit))
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show all", event_id="evt-show-all"))

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "pending", 10), ("U123", "done", 10)]
    assert captured["text"] == "No tasks right now."


def test_clear_tasks_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", lambda user_id, status="pending": {"deleted": 2})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("clear tasks", event_id="evt-clear-tasks"))

    assert response.status_code == 200
    assert captured["text"] == "Cleared 2 pending task(s)."


def test_clear_completed_command(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_clear_tasks(user_id, status="pending"):
        captured["calls"].append((user_id, status))
        return {"deleted": 3}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", fake_clear_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("clear completed", event_id="evt-clear-completed"))

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "done")]
    assert captured["text"] == "Cleared 3 completed task(s)."


def test_clear_done_command_uses_done_status(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_clear_tasks(user_id, status="pending"):
        captured["calls"].append((user_id, status))
        return {"deleted": 0}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", fake_clear_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("clear done", event_id="evt-clear-done"))

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "done")]
    assert captured["text"] == "Cleared 0 completed task(s)."


def test_add_task_command_creates_pending_task(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("add task review the deck", event_id="evt-add-task"))

    assert response.status_code == 200
    assert captured["text"] == "Saved to pending tasks: review the deck"
    assert len(created_tasks) == 1
    assert created_tasks[0]["source_message"] == "add task review the deck"
    assert created_tasks[0]["task_text"] == "review the deck"
    assert created_tasks[0]["assistant_commitment"] == "Saved as a pending task."


def test_add_task_command_returns_existing_pending_task_message_when_deduped(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {
            "id": 1,
            "task_text": "review the deck",
            "deduped": True,
            "created": False,
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("add task review the deck", event_id="evt-add-task-deduped"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Already in pending tasks: review the deck"
    assert len(created_tasks) == 1
    assert created_tasks[0]["task_text"] == "review the deck"


def test_remind_me_request_creates_pending_task(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remind me tomorrow to review the deck", event_id="evt-remind-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Saved to pending tasks: review the deck"
    assert len(created_tasks) == 1
    assert created_tasks[0]["source_message"] == "remind me tomorrow to review the deck"
    assert created_tasks[0]["task_text"] == "review the deck"


def test_remind_me_request_returns_existing_pending_task_message_when_deduped(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {
            "id": 1,
            "task_text": "review the deck",
            "deduped": True,
            "created": False,
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remind me tomorrow to review the deck", event_id="evt-remind-task-deduped"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Already in pending tasks: review the deck"
    assert len(created_tasks) == 1
    assert created_tasks[0]["task_text"] == "review the deck"


def test_done_command_marks_pending_task_done(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "updated": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("done send the invoice", event_id="evt-done-task"))

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_complete_task_command_marks_pending_task_done(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "updated": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("complete task send the invoice", event_id="evt-complete-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_done_command_returns_not_found_message_when_no_pending_match(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {"updated": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-done-task-missing"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: send the invoice"


def test_done_command_handles_malformed_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {"task": {"task_text": "send the invoice"}}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-done-malformed-dict"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: send the invoice"
    assert "Something went wrong" not in captured["text"]


def test_done_command_handles_non_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return ["unexpected"]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-done-nondict"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: send the invoice"
    assert "Something went wrong" not in captured["text"]


def test_i_finished_phrase_marks_pending_task_done(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text, lane=None):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "updated": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("i finished send the invoice", event_id="evt-i-finished-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_thats_done_phrase_marks_pending_task_done(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text, lane=None):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "updated": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("that's done send the invoice", event_id="evt-thats-done-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_thats_without_apostrophe_phrase_marks_pending_task_done(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text, lane=None):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "updated": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("thats done send the invoice", event_id="evt-thats-no-apostrophe-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_remove_done_task_command_removes_completed_task(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        assert status == "done"
        return {
            "deleted": True,
            "task": {
                "task_text": "send the invoice",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove done task send the invoice", event_id="evt-remove-done-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Removed completed task: send the invoice"


def test_remove_completed_task_command_returns_not_found_message(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        assert status == "done"
        return {"deleted": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove completed task send the invoice", event_id="evt-remove-completed-task-missing"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a completed task matching: send the invoice"


def test_remove_task_command_removes_pending_task(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "review the deck"
        assert status == "pending"
        return {
            "deleted": True,
            "task": {
                "task_text": "review the deck",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-task"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Removed pending task: review the deck"


def test_remove_task_command_returns_not_found_message_when_no_pending_match(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "review the deck"
        assert status == "pending"
        return {"deleted": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-task-missing"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: review the deck"


def test_remove_task_command_handles_malformed_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "review the deck"
        assert status == "pending"
        return {"task": {"task_text": "review the deck"}}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-task-malformed-dict"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: review the deck"
    assert "Something went wrong" not in captured["text"]


def test_remove_task_command_handles_non_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending"):
        assert user_id == "U123"
        assert task_text == "review the deck"
        assert status == "pending"
        return None

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-task-nondict"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: review the deck"
    assert "Something went wrong" not in captured["text"]


def test_delete_phrase_removes_pending_task(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending", lane=None):
        assert user_id == "U123"
        assert task_text == "review the deck"
        assert status == "pending"
        return {
            "deleted": True,
            "task": {
                "task_text": "review the deck",
            },
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("delete review the deck", event_id="evt-delete-task-natural"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Removed pending task: review the deck"


def test_clear_tasks_command_handles_malformed_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", lambda user_id, status="pending": {"deleted": "abc"})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("clear tasks", event_id="evt-clear-tasks-malformed"))

    assert response.status_code == 200
    assert captured["text"] == "Cleared 0 pending task(s)."
    assert "Something went wrong" not in captured["text"]


def test_clear_completed_command_handles_non_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", lambda user_id, status="pending": None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("clear completed", event_id="evt-clear-completed-nondict"))

    assert response.status_code == 200
    assert captured["text"] == "Cleared 0 completed task(s)."
    assert "Something went wrong" not in captured["text"]


def test_show_memory_handles_non_list_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", lambda user_id, lane, limit=20: {"content": "bad"})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("show memory", event_id="evt-show-memory-nonlist"))

    assert response.status_code == 200
    assert captured["text"] == "I do not have any saved memory yet in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_show_memory_handles_malformed_items(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    malformed_items = [
        {"content": ""},
        {"visibility": "private"},
        "bad-item",
        {"content": "  "},
    ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", lambda user_id, lane, limit=20: malformed_items)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("show memory", event_id="evt-show-memory-malformed"))

    assert response.status_code == 200
    assert captured["text"] == "I do not have any saved memory yet in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_remember_that_phrase_saves_memory(monkeypatch):
    reset_route_state()
    captured = {}
    calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "private")
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("remember that apples are in the kitchen", event_id="evt-remember-that"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Got it. I'll remember this in the work lane: apples are in the kitchen"
    assert len(calls) == 1
    assert calls[0]["content"] == "apples are in the kitchen"


def test_can_you_remember_this_phrase_saves_memory(monkeypatch):
    reset_route_state()
    captured = {}
    calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "private")
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("can you remember this apples are in the kitchen", event_id="evt-remember-this"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Got it. I'll remember this in the work lane: apples are in the kitchen"
    assert len(calls) == 1
    assert calls[0]["content"] == "apples are in the kitchen"


def test_what_do_you_remember_about_phrase_recalls_memory(monkeypatch):
    reset_route_state()
    captured = {}
    calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(user_id, query, lane, limit=5):
        calls.append((user_id, query, lane, limit))
        return [{"lane": lane, "visibility": "private", "content": "apples are in the kitchen"}]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("what do you remember about apples", event_id="evt-recall-natural"),
    )

    assert response.status_code == 200
    assert calls == [("U123", "apples", "work", 5)]
    assert "Here is what I found:" in captured["text"]
    assert "apples are in the kitchen" in captured["text"]


def test_recall_handles_non_list_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", lambda user_id, query, lane, limit=5: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("recall fruit", event_id="evt-recall-nonlist"))

    assert response.status_code == 200
    assert captured["text"] == "I could not find anything matching that in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_recall_handles_malformed_items(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    malformed_items = [
        {"content": ""},
        {"lane": "work"},
        123,
        {"content": "   "},
    ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", lambda user_id, query, lane, limit=5: malformed_items)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("recall fruit", event_id="evt-recall-malformed"))

    assert response.status_code == 200
    assert captured["text"] == "I could not find anything matching that in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_forget_that_phrase_deletes_memory(monkeypatch):
    reset_route_state()
    captured = {}
    calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_delete_memory_by_query(user_id, query, lane):
        calls.append((user_id, query, lane))
        return {"deleted": True, "lane": lane}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("forget that apples are in the kitchen", event_id="evt-forget-that"),
    )

    assert response.status_code == 200
    assert calls == [("U123", "apples are in the kitchen", "work")]
    assert captured["text"] == "Forgot memory in the work lane matching: apples are in the kitchen"


def test_please_forget_this_phrase_deletes_memory(monkeypatch):
    reset_route_state()
    captured = {}
    calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_delete_memory_by_query(user_id, query, lane):
        calls.append((user_id, query, lane))
        return {"deleted": True, "lane": lane}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("please forget this apples are in the kitchen", event_id="evt-please-forget-this"),
    )

    assert response.status_code == 200
    assert calls == [("U123", "apples are in the kitchen", "work")]
    assert captured["text"] == "Forgot memory in the work lane matching: apples are in the kitchen"


def test_forget_handles_non_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", lambda user_id, query, lane: ["bad"])
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("forget apples", event_id="evt-forget-nondict"))

    assert response.status_code == 200
    assert captured["text"] == "I could not find anything to forget for: apples in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_forget_handles_malformed_dict_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", lambda user_id, query, lane: {"lane": "work"})
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post("/slack/events", json=make_event("forget apples", event_id="evt-forget-malformed"))

    assert response.status_code == 200
    assert captured["text"] == "I could not find anything to forget for: apples in the work lane."
    assert "Something went wrong" not in captured["text"]


def test_normal_chat_message_creates_task_on_commitment(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "On it. I'll proceed with 1, 2, and 3.")
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: True)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("please do 1, 2, and 3", event_id="evt-chat"))

    assert response.status_code == 200
    assert captured["text"] == "On it. I'll proceed with 1, 2, and 3."
    assert len(created_tasks) == 1
    assert created_tasks[0]["source_message"] == "please do 1, 2, and 3"
    assert created_tasks[0]["task_text"] == "please do 1, 2, and 3"


def test_normal_chat_message_skips_duplicate_commitment_task(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {
            "id": 1,
            "task_text": "please do 1, 2, and 3",
            "deduped": True,
            "created": False,
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "On it. I'll proceed with 1, 2, and 3.")
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: True)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("please do 1, 2, and 3", event_id="evt-chat-deduped"))

    assert response.status_code == 200
    assert captured["text"] == "On it. I'll proceed with 1, 2, and 3."
    assert len(created_tasks) == 1
    assert created_tasks[0]["task_text"] == "please do 1, 2, and 3"


def test_normal_chat_message_does_not_create_task_without_commitment(monkeypatch):
    reset_route_state()
    captured = {}
    created_tasks = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        created_tasks.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Here is the completed answer.")
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: False)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("hello bishop", event_id="evt-chat-2"))

    assert response.status_code == 200
    assert captured["text"] == "Here is the completed answer."
    assert created_tasks == []


def test_add_task_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        captured["calls"].append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("add task review lane A", event_id="evt-lane-a", channel_id="C123"),
    )
    client.post(
        "/slack/events",
        json=make_event("add task review lane B", event_id="evt-lane-b", channel_id="C999"),
    )

    assert len(captured["calls"]) == 2

    lanes = [call.get("lane") for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_show_pending_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_tasks(user_id, status="pending", limit=10, lane=None):
        captured["calls"].append((user_id, status, lane))

        if lane == "C123":
            return [{"task_text": "Task in lane A"}]
        if lane == "C999":
            return [{"task_text": "Task in lane B"}]
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("show pending", event_id="evt-show-a", channel_id="C123"),
    )
    assert "Task in lane A" in captured["text"]

    client.post(
        "/slack/events",
        json=make_event("show pending", event_id="evt-show-b", channel_id="C999"),
    )
    assert "Task in lane B" in captured["text"]

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_done_command_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text, lane=None):
        captured["calls"].append((user_id, task_text, lane))
        if lane == "C123":
            return {"updated": True, "task": {"task_text": task_text}}
        return {"updated": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-done-a", channel_id="C123"),
    )
    assert captured["text"] == "Marked done: send the invoice"

    client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-done-b", channel_id="C999"),
    )
    assert captured["text"] == "I could not find a pending task matching: send the invoice"

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_remove_task_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_remove_task(user_id, task_text, status="pending", lane=None):
        captured["calls"].append((user_id, task_text, status, lane))
        if lane == "C123":
            return {"deleted": True, "task": {"task_text": task_text}}
        return {"deleted": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-a", channel_id="C123"),
    )
    assert captured["text"] == "Removed pending task: review the deck"

    client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-remove-b", channel_id="C999"),
    )
    assert captured["text"] == "I could not find a pending task matching: review the deck"

    lanes = [call[3] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_clear_tasks_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_clear_tasks(user_id, status="pending", lane=None):
        captured["calls"].append((user_id, status, lane))
        if lane == "C123":
            return {"deleted": 2}
        if lane == "C999":
            return {"deleted": 1}
        return {"deleted": 0}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_tasks", fake_clear_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("clear tasks", event_id="evt-clear-a", channel_id="C123"),
    )
    assert captured["text"] == "Cleared 2 pending task(s)."

    client.post(
        "/slack/events",
        json=make_event("clear tasks", event_id="evt-clear-b", channel_id="C999"),
    )
    assert captured["text"] == "Cleared 1 pending task(s)."

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_show_all_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_tasks(user_id, status="pending", limit=10, lane=None):
        captured["calls"].append((user_id, status, lane))
        if lane == "C123" and status == "pending":
            return [{"task_text": "pending lane A"}]
        if lane == "C123" and status == "done":
            return [{"task_text": "done lane A"}]
        if lane == "C999" and status == "pending":
            return [{"task_text": "pending lane B"}]
        if lane == "C999" and status == "done":
            return [{"task_text": "done lane B"}]
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_tasks", fake_get_tasks)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("show all", event_id="evt-show-all-a", channel_id="C123"),
    )
    assert "pending lane A" in captured["text"]
    assert "done lane A" in captured["text"]

    client.post(
        "/slack/events",
        json=make_event("show all", event_id="evt-show-all-b", channel_id="C999"),
    )
    assert "pending lane B" in captured["text"]
    assert "done lane B" in captured["text"]

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_same_task_text_can_exist_in_two_lanes(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        return {"ok": True, "ts": "123"}

    def fake_add_task(**kwargs):
        captured["calls"].append(kwargs)
        return {"id": len(captured["calls"])}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_task", fake_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("add task review the deck", event_id="evt-same-task-a", channel_id="C123"),
    )
    client.post(
        "/slack/events",
        json=make_event("add task review the deck", event_id="evt-same-task-b", channel_id="C999"),
    )

    assert len(captured["calls"]) == 2
    assert captured["calls"][0]["task_text"] == "review the deck"
    assert captured["calls"][1]["task_text"] == "review the deck"
    assert captured["calls"][0]["lane"] == "C123"
    assert captured["calls"][1]["lane"] == "C999"


def test_remember_command_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["calls"].append(kwargs)
        return {"id": len(captured["calls"])}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_default_visibility_for_lane",
        lambda lane: "private",
    )
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("remember apples", event_id="evt-remember-a", channel_id="C123"),
    )
    assert captured["text"] == "Got it. I'll remember this in the C123 lane: apples"

    client.post(
        "/slack/events",
        json=make_event("remember oranges", event_id="evt-remember-b", channel_id="C999"),
    )
    assert captured["text"] == "Got it. I'll remember this in the C999 lane: oranges"

    assert len(captured["calls"]) == 2
    assert captured["calls"][0]["lane"] == "C123"
    assert captured["calls"][0]["content"] == "apples"
    assert captured["calls"][1]["lane"] == "C999"
    assert captured["calls"][1]["content"] == "oranges"


def test_show_memory_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_memories(user_id, lane, limit=20):
        captured["calls"].append((user_id, lane, limit))
        if lane == "C123":
            return [{"lane": "C123", "visibility": "private", "content": "apples"}]
        if lane == "C999":
            return [{"lane": "C999", "visibility": "private", "content": "oranges"}]
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-show-memory-a", channel_id="C123"),
    )
    assert "Here is what I remember in the C123 lane:" in captured["text"]
    assert "apples" in captured["text"]

    client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-show-memory-b", channel_id="C999"),
    )
    assert "Here is what I remember in the C999 lane:" in captured["text"]
    assert "oranges" in captured["text"]

    lanes = [call[1] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_recall_command_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(user_id, query, lane, limit=5):
        captured["calls"].append((user_id, query, lane, limit))
        if lane == "C123":
            return [{"lane": "C123", "visibility": "private", "content": "apples are in kitchen"}]
        if lane == "C999":
            return [{"lane": "C999", "visibility": "private", "content": "oranges are in studio"}]
        return []

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("recall fruit", event_id="evt-recall-a", channel_id="C123"),
    )
    assert "Here is what I found:" in captured["text"]
    assert "apples are in kitchen" in captured["text"]

    client.post(
        "/slack/events",
        json=make_event("recall fruit", event_id="evt-recall-b", channel_id="C999"),
    )
    assert "Here is what I found:" in captured["text"]
    assert "oranges are in studio" in captured["text"]

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_forget_command_is_lane_aware(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_delete_memory_by_query(user_id, query, lane):
        captured["calls"].append((user_id, query, lane))
        if lane == "C123":
            return {"deleted": True, "lane": "C123"}
        return {"deleted": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "get_lane_from_channel",
        lambda channel_id, resolver=None: channel_id,
    )

    client.post(
        "/slack/events",
        json=make_event("forget apples", event_id="evt-forget-a", channel_id="C123"),
    )
    assert captured["text"] == "Forgot memory in the C123 lane matching: apples"

    client.post(
        "/slack/events",
        json=make_event("forget apples", event_id="evt-forget-b", channel_id="C999"),
    )
    assert captured["text"] == "I could not find anything to forget for: apples in the C999 lane."

    lanes = [call[2] for call in captured["calls"]]
    assert "C123" in lanes
    assert "C999" in lanes


def test_shared_memory_visible_across_users_same_lane(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    memory_store = []

    def fake_add_memory(**kwargs):
        memory_store.append(kwargs)
        return {"id": len(memory_store)}

    def fake_get_memories(user_id, lane, limit=20):
        return [
            {
                "content": m["content"],
                "lane": m["lane"],
                "visibility": m["visibility"],
                "owner_user_id": m["user_id"],
            }
            for m in memory_store
            if m["lane"] == lane and m["visibility"] == "shared"
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "shared")
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "family")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    client.post(
        "/slack/events",
        json=make_event("remember we have dinner at 7", event_id="evt-shared-matt", user_id="U_MATT"),
    )

    client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-shared-carmen", user_id="U_CARMEN"),
    )

    assert any("dinner at 7" in r for r in captured["responses"])


def test_private_memory_not_visible_across_users(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    memory_store = []

    def fake_add_memory(**kwargs):
        memory_store.append(kwargs)
        return {"id": len(memory_store)}

    def fake_get_memories(user_id, lane, limit=20):
        return [
            {
                "content": m["content"],
                "lane": m["lane"],
                "visibility": m["visibility"],
                "owner_user_id": m["user_id"],
            }
            for m in memory_store
            if m["lane"] == lane
            and (m["visibility"] == "shared" or m["user_id"] == user_id)
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "private")
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "family")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    client.post(
        "/slack/events",
        json=make_event("remember my password is 1234", event_id="evt-private-matt", user_id="U_MATT"),
    )

    client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-private-carmen", user_id="U_CARMEN"),
    )

    assert "password is 1234" not in captured["responses"][-1]


def test_user_cannot_delete_another_users_memory(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    memory_store = [{"user_id": "U_MATT", "content": "secret note", "lane": "family"}]

    def fake_delete_memory_by_query(user_id, query, lane):
        for m in memory_store:
            if m["content"] == query and m["user_id"] == user_id:
                memory_store.remove(m)
                return {"deleted": True, "lane": lane}
        return {"deleted": False}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "family")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    client.post(
        "/slack/events",
        json=make_event("forget secret note", event_id="evt-delete-other", user_id="U_CARMEN"),
    )

    assert any("could not find anything to forget" in r.lower() for r in captured["responses"])


def test_show_memory_suppresses_boilerplate_by_default(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_get_memories(user_id, lane, limit=20):
        return [
            {
                "content": "dinner at 7",
                "lane": lane,
                "visibility": "shared",
                "owner_user_id": "matt",
                "category": "note",
            },
            {
                "content": "User's name is Matt.",
                "lane": lane,
                "visibility": "shared",
                "owner_user_id": "matt",
                "category": "profile",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "shared")
    monkeypatch.setattr(
        slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "family"
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    client.post(
        "/slack/events",
        json=make_event("show memory", event_id="evt-show-mem-default", user_id="U_MATT"),
    )

    assert captured["responses"], "expected a response"
    response = captured["responses"][-1]
    assert "dinner at 7" in response
    assert "User's name is Matt." not in response


def test_show_all_memory_includes_boilerplate(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_get_memories(user_id, lane, limit=20):
        return [
            {
                "content": "dinner at 7",
                "lane": lane,
                "visibility": "shared",
                "owner_user_id": "matt",
                "category": "note",
            },
            {
                "content": "User's name is Matt.",
                "lane": lane,
                "visibility": "shared",
                "owner_user_id": "matt",
                "category": "profile",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_default_visibility_for_lane", lambda lane: "shared")
    monkeypatch.setattr(
        slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "family"
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    client.post(
        "/slack/events",
        json=make_event("show all memory", event_id="evt-show-all-mem", user_id="U_MATT"),
    )

    assert captured["responses"], "expected a response"
    response = captured["responses"][-1]
    assert "dinner at 7" in response
    assert "User's name is Matt." in response
