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
# RECALL WITH RESULTS
# ----------------------------

def test_recall_command_formats_results(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(*args, **kwargs):
        return [
            {
                "content": "dinner at 7",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            },
            {
                "content": "buy gift",
                "lane": "family",
                "visibility": "private",
                "owner_user_id": "carmen",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt" if user_id == "matt" else "Carmen",
    )

    response = client.post(
        "/slack/events",
        json=make_event("recall dinner", event_id="evt-recall-1"),
    )

    assert response.status_code == 200
    assert "* Matt shared in family: dinner at 7" in captured["text"]
    assert "* Carmen private in family: buy gift" in captured["text"]


# ----------------------------
# RECALL (ALT PHRASE)
# ----------------------------

def test_what_do_you_remember_about_command_formats_results(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(*args, **kwargs):
        return [
            {
                "content": "vacation in June",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            }
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = client.post(
        "/slack/events",
        json=make_event("what do you remember about vacation", event_id="evt-recall-2"),
    )

    assert response.status_code == 200
    assert "* Matt shared in family: vacation in June" in captured["text"]


# ----------------------------
# NO RESULTS
# ----------------------------

def test_recall_command_handles_no_results(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")

    response = client.post(
        "/slack/events",
        json=make_event("recall anniversary", event_id="evt-recall-3"),
    )

    assert response.status_code == 200
    assert "could not find anything" in captured["text"].lower()


# ----------------------------
# FILTER INVALID ITEMS
# ----------------------------

def test_recall_command_filters_invalid_items(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(*args, **kwargs):
        return [
            {"content": ""},
            {"no_content": True},
            {
                "content": "real item",
                "lane": "family",
                "visibility": "shared",
                "owner_user_id": "matt",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = client.post(
        "/slack/events",
        json=make_event("recall real", event_id="evt-recall-4"),
    )

    assert response.status_code == 200
    assert "* Matt shared in family: real item" in captured["text"]


# ----------------------------
# MISSING OWNER
# ----------------------------

def test_recall_command_handles_missing_owner(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_search_memories(*args, **kwargs):
        return [
            {
                "content": "orphaned note",
                "lane": "family",
                "visibility": "shared",
            }
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "search_memories", fake_search_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *args, **kwargs: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Unknown",
    )

    response = client.post(
        "/slack/events",
        json=make_event("recall orphaned", event_id="evt-recall-5"),
    )

    assert response.status_code == 200
    assert "* Unknown shared in family: orphaned note" in captured["text"]
