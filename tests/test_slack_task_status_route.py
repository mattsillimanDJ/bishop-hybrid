from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route


client = TestClient(app)


def make_event(
    text: str,
    event_id: str = "evt-1",
    user_id: str = "U123",
    channel_id: str = "C123",
):
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


def test_done_command_accepts_status_updated_without_updated_flag(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "status": "updated",
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
        json=make_event("done send the invoice", event_id="evt-status-done-1"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Marked done: send the invoice"


def test_done_command_accepts_status_not_found_without_updated_flag(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_mark_task_done(user_id, task_text):
        assert user_id == "U123"
        assert task_text == "send the invoice"
        return {
            "status": "not_found",
            "task": None,
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "mark_task_done", fake_mark_task_done)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("done send the invoice", event_id="evt-status-done-2"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: send the invoice"


def test_remove_task_command_accepts_status_deleted_without_deleted_flag(monkeypatch):
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
            "status": "deleted",
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
        json=make_event("remove task review the deck", event_id="evt-status-remove-1"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Removed pending task: review the deck"


def test_remove_done_task_command_accepts_status_deleted_without_deleted_flag(monkeypatch):
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
            "status": "deleted",
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
        json=make_event("remove done task send the invoice", event_id="evt-status-remove-2"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Removed completed task: send the invoice"


def test_remove_task_command_accepts_status_not_found_without_deleted_flag(monkeypatch):
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
            "status": "not_found",
            "task": None,
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "remove_task", fake_remove_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("remove task review the deck", event_id="evt-status-remove-3"),
    )

    assert response.status_code == 200
    assert captured["text"] == "I could not find a pending task matching: review the deck"
