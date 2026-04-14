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


# ----------------------------
# DELETE SUCCESS CASES
# ----------------------------

def test_forget_command_deletes_memory(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        captured["lane"] = kwargs.get("lane")
        return {"deleted": True, "lane": "family"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("forget dinner at 7"))

    assert captured["query"] == "dinner at 7"
    assert captured["lane"] == "family"
    assert "Forgot memory in the family lane matching: dinner at 7" in captured["text"]


def test_forget_that_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        return {"deleted": True, "lane": "family"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("forget that dinner at 7"))

    assert captured["query"] == "dinner at 7"
    assert "Forgot memory in the family lane matching: dinner at 7" in captured["text"]


def test_forget_this_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        return {"deleted": True, "lane": "family"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("forget this dinner at 7"))

    assert captured["query"] == "dinner at 7"
    assert "Forgot memory in the family lane matching: dinner at 7" in captured["text"]


def test_stop_remembering_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        return {"deleted": True, "lane": "family"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("stop remembering dinner at 7"))

    assert captured["query"] == "dinner at 7"
    assert "Forgot memory in the family lane matching: dinner at 7" in captured["text"]


# ----------------------------
# NO MATCH CASE
# ----------------------------

def test_forget_command_handles_no_match(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        captured["query"] = kwargs.get("query")
        return {"deleted": False, "lane": "family"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("forget anniversary plans"))

    assert captured["query"] == "anniversary plans"
    assert "could not find anything to forget" in captured["text"].lower()


# ----------------------------
# LANE FROM RESULT
# ----------------------------

def test_forget_command_uses_deleted_lane(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True}

    def fake_delete_memory_by_query(*args, **kwargs):
        return {"deleted": True, "lane": "dj"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "delete_memory_by_query", fake_delete_memory_by_query)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    client.post("/slack/events", json=make_event("forget club opener"))

    assert "dj lane" in captured["text"]
