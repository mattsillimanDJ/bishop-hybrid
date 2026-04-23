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


def install_common_fakes(monkeypatch, captured, memories):
    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", lambda *a, **kw: list(memories))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda *a, **kw: "family")
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt" if user_id == "matt" else "Carmen",
    )


def test_show_working_memory_returns_only_working_items(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "dinner at 7",
            "category": "note",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
        {
            "content": "Carmen is Matt's wife",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show working memory", event_id="evt-working"),
    )

    assert response.status_code == 200
    text = captured["text"]
    assert "Working memory in the family lane:" in text
    assert "dinner at 7" in text
    assert "Carmen is Matt's wife" not in text
    assert "Background profile" not in text


def test_show_background_profile_returns_only_background_items(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "dinner at 7",
            "category": "note",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
        {
            "content": "Carmen is Matt's wife",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show background profile", event_id="evt-background"),
    )

    assert response.status_code == 200
    text = captured["text"]
    assert "Background profile in the family lane:" in text
    assert "Carmen is Matt's wife" in text
    assert "dinner at 7" not in text
    assert "Working memory" not in text


def test_show_working_memory_empty_returns_clean_empty_message(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "Carmen is Matt's wife",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show working memory", event_id="evt-working-empty"),
    )

    assert response.status_code == 200
    assert (
        captured["text"]
        == "I do not have any working memory yet in the family lane."
    )


def test_show_background_profile_empty_returns_clean_empty_message(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "dinner at 7",
            "category": "note",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show background profile", event_id="evt-background-empty"),
    )

    assert response.status_code == 200
    assert (
        captured["text"]
        == "I do not have any background profile yet in the family lane."
    )


def test_show_background_profile_suppresses_boilerplate_by_default(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "User's name is Matt.",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
        {
            "content": "Matt is an advertising executive and DJ.",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
        {
            "content": "Carmen is Matt's wife",
            "category": "profile",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show background profile", event_id="evt-bg-boiler"),
    )

    assert response.status_code == 200
    text = captured["text"]
    assert "Background profile in the family lane:" in text
    assert "Carmen is Matt's wife" in text
    assert "User's name is Matt" not in text
    assert "advertising executive" not in text


def test_show_working_memory_suppresses_boilerplate_by_default(monkeypatch):
    reset_route_state()
    captured = {}

    memories = [
        {
            "content": "Matt wants Bishop to feel like a personal AI operating system, not a generic chatbot.",
            "category": "preference",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
        },
        {
            "content": "dinner at 7",
            "category": "note",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
    ]

    install_common_fakes(monkeypatch, captured, memories)

    response = client.post(
        "/slack/events",
        json=make_event("show working memory", event_id="evt-working-boiler"),
    )

    assert response.status_code == 200
    text = captured["text"]
    assert "Working memory in the family lane:" in text
    assert "dinner at 7" in text
    assert "personal AI operating system" not in text
