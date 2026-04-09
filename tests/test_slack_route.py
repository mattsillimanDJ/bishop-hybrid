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
    assert "show tasks" in captured["text"]
    assert "add task" in captured["text"]
    assert "remind me" in captured["text"]


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
    monkeypatch.setattr(slack_route, "get_tasks", lambda user_id, status="pending", limit=10: [{"task_text": "Do the thing"}])
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("status", event_id="evt-status"))

    assert response.status_code == 200
    assert "*Pending tasks:* 1" in captured["text"]


def test_show_pending_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_tasks",
        lambda user_id, status="pending", limit=10: [
            {
                "created_at": "2026-04-03T20:00:00+00:00",
                "task_text": "Do 1, 2, and 3",
                "assistant_commitment": "On it. I'll proceed with 1, 2, and 3.",
            }
        ],
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("show pending", event_id="evt-show-pending"))

    assert response.status_code == 200
    assert "Pending tasks:" in captured["text"]
    assert "Do 1, 2, and 3" in captured["text"]


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
