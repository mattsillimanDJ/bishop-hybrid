import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import slack as slack_route
from app.services.artifact_service import ArtifactResult


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


def make_message_event(
    text: str,
    event_id: str = "evt-message-1",
    user_id: str = "U123",
    channel_id: str = "D123",
    channel_type: str = "im",
):
    return {
        "type": "event_callback",
        "event_id": event_id,
        "event": {
            "type": "message",
            "user": user_id,
            "channel": channel_id,
            "channel_type": channel_type,
            "text": text,
            "ts": "123.456",
        },
    }


def reset_route_state():
    slack_route.processed_event_ids.clear()
    slack_route.recent_message_fingerprints.clear()


def test_post_message_preserves_default_slack_unfurl_behavior(monkeypatch):
    captured = {}

    class FakeSlackClient:
        def chat_postMessage(self, **kwargs):
            captured.update(kwargs)
            return {"ts": "123"}

    monkeypatch.setattr(slack_route.settings, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_route, "slack_client", FakeSlackClient())

    response = slack_route.post_message("C123", "hello https://example.com")

    assert response == {"ok": True, "ts": "123"}
    assert captured == {"channel": "C123", "text": "hello https://example.com"}


def test_post_message_can_disable_slack_unfurls(monkeypatch):
    captured = {}

    class FakeSlackClient:
        def chat_postMessage(self, **kwargs):
            captured.update(kwargs)
            return {"ts": "123"}

    monkeypatch.setattr(slack_route.settings, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_route, "slack_client", FakeSlackClient())

    response = slack_route.post_message(
        "C123",
        "research https://example.com",
        unfurl_links=False,
        unfurl_media=False,
    )

    assert response == {"ok": True, "ts": "123"}
    assert captured == {
        "channel": "C123",
        "text": "research https://example.com",
        "unfurl_links": False,
        "unfurl_media": False,
    }


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


def test_ignores_channel_message_without_app_mention(monkeypatch):
    monkeypatch.setattr(slack_route.settings, "BISHOP_AUTO_LISTEN_CHANNELS", "")

    response = client.post(
        "/slack/events",
        json=make_message_event(
            "hello",
            event_id="evt-non-mention",
            channel_id="C123",
            channel_type="channel",
        ),
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


def test_followup_uses_working_session_context(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured.setdefault("posted", []).append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message, working_context=""):
        captured["message_to_model"] = message
        captured["working_context"] = working_context
        return "Next move: turn the StemLab plan into a one-page MVP test."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "stemlab")
    monkeypatch.setattr(
        slack_route,
        "get_working_session_context",
        lambda user_id, lane, focus: (
            "Recent working session context:\n"
            "User: We should validate StemLab with an Ableton stem workflow MVP.\n"
            "Bishop: Next move: write the smallest MVP test plan."
        ),
    )
    monkeypatch.setattr(slack_route, "append_working_session_turn", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "stemlab")

    response = client.post(
        "/slack/events",
        json=make_event("let's do the next move", event_id="evt-session-context"),
    )

    assert response.status_code == 200
    assert "StemLab" in captured["working_context"]
    assert "let's do the next move" in captured["message_to_model"]
    assert captured["posted"] == ["Next move: turn the StemLab plan into a one-page MVP test."]


def test_dm_message_without_app_mention_is_processed(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "DM reply."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "append_working_session_turn", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "dm")

    response = client.post(
        "/slack/events",
        json=make_message_event("continue the plan", event_id="evt-dm-no-mention"),
    )

    assert response.status_code == 200
    assert captured["channel"] == "D123"
    assert captured["text"] == "DM reply."
    assert "continue the plan" in captured["message_to_model"]


def test_channel_message_without_app_mention_is_ignored(monkeypatch):
    reset_route_state()

    def fail_post_message(channel, text):
        raise AssertionError("Channel messages without a mention should be ignored.")

    def fail_generate_reply(*args, **kwargs):
        raise AssertionError("Channel messages without a mention should not reach the model.")

    monkeypatch.setattr(slack_route, "post_message", fail_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route.settings, "BISHOP_AUTO_LISTEN_CHANNELS", "")

    response = client.post(
        "/slack/events",
        json=make_message_event(
            "normal channel chatter",
            event_id="evt-channel-without-mention",
            channel_id="C123",
            channel_type="channel",
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_trusted_channel_message_without_app_mention_is_processed(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Trusted channel reply."

    monkeypatch.setattr(slack_route.settings, "BISHOP_AUTO_LISTEN_CHANNELS", "C123")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "append_working_session_turn", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "trusted")

    response = client.post(
        "/slack/events",
        json=make_message_event(
            "continue the channel plan",
            event_id="evt-trusted-channel-no-mention",
            channel_id="C123",
            channel_type="channel",
        ),
    )

    assert response.status_code == 200
    assert captured["channel"] == "C123"
    assert captured["text"] == "Trusted channel reply."
    assert "continue the channel plan" in captured["message_to_model"]


def test_trusted_channel_message_can_match_normalized_channel_name(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Named trusted channel reply."

    monkeypatch.setattr(slack_route.settings, "BISHOP_AUTO_LISTEN_CHANNELS", "#Bishop Private")
    monkeypatch.setattr(slack_route, "resolve_slack_channel_name", lambda channel_id: "bishop-private")
    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "append_working_session_turn", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "trusted")

    response = client.post(
        "/slack/events",
        json=make_message_event(
            "continue by channel name",
            event_id="evt-trusted-channel-name-no-mention",
            channel_id="C456",
            channel_type="channel",
        ),
    )

    assert response.status_code == 200
    assert captured["channel"] == "C456"
    assert captured["text"] == "Named trusted channel reply."
    assert "continue by channel name" in captured["message_to_model"]


def test_slack_docx_export_missing_content_returns_useful_response(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fail_create_artifact(*args, **kwargs):
        raise AssertionError("Artifact should not be created without content.")

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "create_artifact", fail_create_artifact)
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("make this a word doc", event_id="evt-docx-missing-content"),
    )

    assert response.status_code == 200
    assert captured["channel"] == "C123"
    assert "I need content to export" in captured["text"]
    assert "make this a Word doc" in captured["text"]


def test_slack_xlsx_export_upload_failure_returns_local_file_fallback(monkeypatch, tmp_path):
    reset_route_state()
    captured = {}
    artifact_path = tmp_path / "bishop_artifact_test.xlsx"
    artifact_path.write_text("placeholder")

    def fake_post_message(channel, text):
        captured["channel"] = channel
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_create_artifact(kind, content):
        captured["artifact_kind"] = kind
        captured["artifact_content"] = content
        return ArtifactResult(
            kind="xlsx",
            path=artifact_path,
            filename=artifact_path.name,
        )

    def fake_upload_file_to_slack(**kwargs):
        captured["upload_kwargs"] = kwargs
        return {"ok": False, "error": "missing_scope"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "create_artifact", fake_create_artifact)
    monkeypatch.setattr(slack_route, "upload_file_to_slack", fake_upload_file_to_slack)
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "make this an excel file: Name,Status\nBishop,Ready",
            event_id="evt-xlsx-upload-failure",
        ),
    )

    assert response.status_code == 200
    assert captured["artifact_kind"] == "xlsx"
    assert captured["artifact_content"] == "Name,Status\nBishop,Ready"
    assert captured["upload_kwargs"]["channel"] == "C123"
    assert captured["upload_kwargs"]["file_path"] == str(artifact_path)
    assert captured["channel"] == "C123"
    assert "could not upload it to Slack" in captured["text"]
    assert str(artifact_path) in captured["text"]
    assert "files:write" in captured["text"]


@pytest.mark.parametrize(
    "raw_text,expected",
    [
        ("@Bishop Hybrid status", "status"),
        ("Bishop Hybrid status", "status"),
        ("bishop status", "status"),
        ("bishop_hybrid status", "status"),
    ],
)
def test_bot_name_prefixes_are_normalized(raw_text, expected):
    assert slack_route.normalize_user_text_for_slack_event(raw_text) == expected


def test_normal_generated_slack_reply_receives_concise_style_instruction(monkeypatch):
    reset_route_state()
    captured = {"posted": []}

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Short answer."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("what should I do next?", event_id="evt-slack-style-normal"),
    )

    assert response.status_code == 200
    assert captured["message_to_model"].startswith("Slack style:")
    assert "answer naturally and concisely" in captured["message_to_model"]
    assert "For simple questions, use 1 to 4 short paragraphs or bullets" in captured["message_to_model"]
    assert "with 3 to 5 bullets max" in captured["message_to_model"]
    assert "prefer one recommendation, up to 3 priorities, and one clear next move" in captured["message_to_model"]
    assert "User message:\nwhat should I do next?" in captured["message_to_model"]
    assert captured["posted"] == ["Short answer."]


def test_simple_generated_slack_question_does_not_send_working_message(monkeypatch):
    reset_route_state()
    posted = []

    def fake_post_message(channel, text):
        posted.append(text)
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "Use the shortest useful answer.")
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("can you summarize the plan?", event_id="evt-simple-no-working"),
    )

    assert response.status_code == 200
    assert posted == ["Use the shortest useful answer."]


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
    assert "Memory:" in captured["text"]
    assert "Tasks:" in captured["text"]
    assert "Modes:" in captured["text"]
    assert "* mode cmo" in captured["text"]
    assert "* mode creative" in captured["text"]
    assert "* mode stemlab" in captured["text"]
    assert "* mode product" in captured["text"]
    assert "* modes" in captured["text"]
    assert "* show modes" in captured["text"]
    assert "* what mode should I use" in captured["text"]
    assert "* recommend mode" in captured["text"]
    assert "* show mode\n* modes\n* show modes" in captured["text"]
    assert "* show mode\n\n* modes" not in captured["text"]
    assert "CMO / Creative examples:" in captured["text"]
    assert "* concept TV and social ideas for July 4" in captured["text"]
    assert "* diagnose this campaign" in captured["text"]
    assert "* give me a campaign spine" in captured["text"]
    assert "* turn this into paid social tests" in captured["text"]
    assert "* write Veo prompts for this idea" in captured["text"]
    assert "StemLab:" in captured["text"]
    assert "* stemlab" in captured["text"]
    assert "* stemlab plan" in captured["text"]
    assert "* stemlab next" in captured["text"]
    assert "* stemlab mvp" in captured["text"]
    assert "* stemlab founder" in captured["text"]
    assert "* stemlab product" in captured["text"]
    assert "* stemlab positioning" in captured["text"]
    assert "* stemlab customer" in captured["text"]
    assert "* stemlab validation" in captured["text"]
    assert "* stemlab assumptions" in captured["text"]
    assert "* stemlab research" in captured["text"]
    assert "* stemlab ableton research" in captured["text"]
    assert "* stemlab reddit research" in captured["text"]
    assert "* stemlab competitor research" in captured["text"]
    assert "* stemlab technical research" in captured["text"]
    assert "* stemlab what not to build" in captured["text"]
    assert "* stemlab research questions" in captured["text"]
    assert "* stemlab prototype plan" in captured["text"]
    assert "* stemlab codex task" in captured["text"]
    assert "Research:" in captured["text"]
    assert "* research" in captured["text"]
    assert "* research status" in captured["text"]
    assert "* stemlab web research" in captured["text"]
    assert "* stemlab reddit search plan" in captured["text"]
    assert "* stemlab source backed finding" in captured["text"]
    assert "System:" in captured["text"]
    assert "show lane" in captured["text"]
    assert "what lane am i in" in captured["text"]
    assert "show tasks" in captured["text"]
    assert "show pending" in captured["text"]
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
    assert "show working memory" in captured["text"]
    assert "show background profile" in captured["text"]
    assert "forget exact memory ..." in captured["text"]
    assert "status" in captured["text"]


def test_modes_command_returns_live_mode_guide(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("modes", event_id="evt-modes"))

    assert response.status_code == 200
    text = captured["text"]
    assert text.startswith("Live modes:")
    assert "* default -" in text
    assert "* work -" in text
    assert "* personal -" in text
    assert "* website -" in text
    assert "* cmo -" in text
    assert "* creative -" in text
    assert "* stemlab -" in text
    assert "* product -" in text
    assert "mode concept" in text
    assert "write Veo prompts for this idea" in text
    assert "founder" not in text.lower()
    assert "Use `show mode` to see the current mode." in text


def test_show_modes_command_returns_live_mode_guide(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("show modes", event_id="evt-show-modes")
    )

    assert response.status_code == 200
    assert captured["text"] == slack_route.mode_guide_text()


def test_what_mode_should_i_use_returns_mode_recommendation(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("what mode should I use", event_id="evt-what-mode-should-i-use"),
    )

    assert response.status_code == 200
    text = captured["text"]
    assert text == slack_route.mode_recommendation_text()
    assert text.startswith("Choose a mode based on what you are trying to do:")
    assert "* default: use for normal mixed questions" in text
    assert "* work: use for client, production, vendor, and execution decisions" in text
    assert "* personal: use for family, relationship, life admin, and personal planning" in text
    assert "* website: use for site structure, copy, UX, SEO, and launch planning" in text
    assert "* cmo: use for marketing strategy, positioning, channels, creative, budget, and measurement" in text
    assert "* creative: use for TV/social concepts, campaign platforms, scripts, paid social tests, retail ideas, and AI video prompts" in text
    assert "* stemlab: use for EDM product, stems, Ableton, music workflow, and DJ/producer output" in text
    assert "* product: use for product ideas, MVP scope, workflows, monetization, and tradeoffs" in text
    assert text.endswith("Tell me what you are working on and I can suggest the best mode.")
    assert "founder" not in text.lower()


def test_recommend_mode_returns_same_mode_recommendation(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("recommend mode", event_id="evt-recommend-mode")
    )

    assert response.status_code == 200
    assert captured["text"] == slack_route.mode_recommendation_text()
    assert "founder" not in captured["text"].lower()


def test_stemlab_command_returns_project_overview(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("stemlab", event_id="evt-stemlab"))

    assert response.status_code == 200
    text = captured["text"]
    assert text == slack_route.stemlab_overview_text()
    assert "StemLab is Matt's AI product idea for DJs, EDM producers, remixers, and creators." in text
    assert "It is not just Suno for EDM." in text
    assert "producer-ready stems and workflows" in text
    assert "Ableton-ready material" in text
    assert "founder mode" not in text.lower()
    assert "Stem Maker" not in text


def test_stemlab_plan_command_returns_structured_plan(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("stemlab plan", event_id="evt-stemlab-plan")
    )

    assert response.status_code == 200
    text = captured["text"]
    assert text == slack_route.stemlab_plan_text()
    assert text.startswith("StemLab product plan:")
    assert "* User:" in text
    assert "* Problem:" in text
    assert "* Wedge:" in text
    assert "* MVP:" in text
    assert "* What not to build yet:" in text
    assert "* Next decisions:" in text
    assert "founder mode" not in text.lower()
    assert "Stem Maker" not in text


def test_stemlab_next_command_returns_next_actions(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("stemlab next", event_id="evt-stemlab-next")
    )

    assert response.status_code == 200
    text = captured["text"]
    assert text == slack_route.stemlab_next_text()
    assert text.startswith("Next 5 StemLab actions:")
    assert "1. Define the first user:" in text
    assert "5. Test the workflow" in text
    assert "founder mode" not in text.lower()
    assert "Stem Maker" not in text


def test_stemlab_mvp_command_returns_mvp_workflow(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("stemlab mvp", event_id="evt-stemlab-mvp")
    )

    assert response.status_code == 200
    text = captured["text"]
    assert text == slack_route.stemlab_mvp_text()
    assert text.startswith("Smallest useful StemLab MVP workflow:")
    assert "User describes a track idea or uploads audio." in text
    assert "It detects BPM and key." in text
    assert "It exports an Ableton-ready stem pack" in text
    assert "Validate workflow quality before trying to train a giant model." in text
    assert "founder mode" not in text.lower()
    assert "Stem Maker" not in text


def test_stemlab_strategy_commands_return_expected_labels(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    commands_and_labels = [
        ("stemlab founder", "StemLab founder lens:"),
        ("stemlab product", "StemLab product lens:"),
        ("stemlab positioning", "StemLab positioning lens:"),
        ("stemlab customer", "StemLab customer lens:"),
        ("stemlab validation", "StemLab validation lens:"),
        ("stemlab assumptions", "StemLab assumption stack:"),
    ]

    for index, (command, label) in enumerate(commands_and_labels, start=1):
        response = client.post(
            "/slack/events",
            json=make_event(command, event_id=f"evt-stemlab-strategy-{index}"),
        )
        assert response.status_code == 200
        assert captured["responses"][-1].startswith(label)

    assert len(captured["responses"]) == len(commands_and_labels)


def test_stemlab_strategy_command_does_not_trigger_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab founder", event_id="evt-stemlab-founder-no-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab founder lens:")
    assert captured["memories"] == []


def test_stemlab_research_commands_return_expected_labels(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    commands_and_labels = [
        ("stemlab research", "StemLab research plan:"),
        ("stemlab ableton research", "StemLab Ableton research plan:"),
        ("stemlab reddit research", "StemLab Reddit/forum research plan:"),
        ("stemlab competitor research", "StemLab competitor research plan:"),
        ("stemlab technical research", "StemLab technical research plan:"),
        ("stemlab what not to build", "StemLab what-not-to-build list:"),
        ("stemlab research questions", "StemLab research questions:"),
        ("stemlab prototype plan", "StemLab prototype plan"),
        ("stemlab codex task", "StemLab Codex task"),
    ]

    for index, (command, label) in enumerate(commands_and_labels, start=1):
        response = client.post(
            "/slack/events",
            json=make_event(command, event_id=f"evt-stemlab-research-{index}"),
        )
        assert response.status_code == 200
        assert captured["responses"][-1].startswith(label)

    assert len(captured["responses"]) == len(commands_and_labels)


def test_stemlab_prototype_plan_command_returns_expected_sections(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("StEmLaB PrOtOtYpE PlAn", event_id="evt-stemlab-prototype-plan"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab prototype plan")
    assert "Prototype goal:" in captured["text"]
    assert "User problem:" in captured["text"]
    assert "MVP workflow:" in captured["text"]
    assert "Technical approach:" in captured["text"]
    assert "What to test this week:" in captured["text"]
    assert "Open questions:" in captured["text"]
    assert "Next Codex task:" in captured["text"]
    assert "Do we need Ableton export support in v0.1 or later?" in captured["text"]
    assert "Create a separate StemLab prototype plan document or repo scaffold" in captured["text"]


def test_stemlab_prototype_plan_command_does_not_trigger_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab prototype plan", event_id="evt-stemlab-prototype-plan-no-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab prototype plan")
    assert captured["memories"] == []


def test_stemlab_codex_task_command_returns_expected_sections(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("StEmLaB CoDeX TaSk", event_id="evt-stemlab-codex-task"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab Codex task")
    assert "Goal:" in captured["text"]
    assert "Context:" in captured["text"]
    assert "Build:" in captured["text"]
    assert "MVP endpoint ideas:" in captured["text"]
    assert "Do not build yet:" in captured["text"]
    assert "Validation:" in captured["text"]
    assert "First Codex instruction:" in captured["text"]
    assert "stemlab_prototype" in captured["text"]
    assert "Do not add Demucs yet." in captured["text"]


def test_stemlab_codex_task_command_does_not_trigger_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab codex task", event_id="evt-stemlab-codex-task-no-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab Codex task")
    assert captured["memories"] == []


def test_research_commands_return_expected_labels(monkeypatch):
    reset_route_state()
    captured = {"responses": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(
        slack_route,
        "validate_research_config",
        lambda: (False, "RESEARCH_PROVIDER is not configured", "none"),
    )

    commands_and_labels = [
        ("research", "Bishop research layer:"),
        ("research status", "Bishop research status:"),
        ("stemlab web research", "StemLab web research workflow:"),
        ("stemlab reddit search plan", "StemLab Reddit search plan:"),
        ("stemlab source backed finding", "StemLab source-backed finding format:"),
    ]

    for index, (command, label) in enumerate(commands_and_labels, start=1):
        response = client.post(
            "/slack/events",
            json=make_event(command, event_id=f"evt-research-v1-{index}"),
        )
        assert response.status_code == 200
        assert captured["responses"][-1].startswith(label)

    assert "Live web/MCP execution is not wired yet." in captured["responses"][1]
    assert "This is a workflow unless live search tools are wired." in captured["responses"][2]
    assert "r/ableton" in captured["responses"][3]
    assert "Findings should only be saved when a source is available." in captured["responses"][4]
    assert len(captured["responses"]) == len(commands_and_labels)


def test_research_status_reports_unavailable_without_provider(monkeypatch):
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
        "validate_research_config",
        lambda: (False, "RESEARCH_PROVIDER is not configured", "none"),
    )

    response = client.post(
        "/slack/events",
        json=make_event("research status", event_id="evt-research-status-unavailable"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("Bishop research status:")
    assert "Live web/MCP execution is not wired yet." in captured["text"]
    assert "RESEARCH_PROVIDER is not configured" in captured["text"]


def test_web_research_command_returns_unavailable_without_provider(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {"ok": True, "ts": "123"}

    def fake_run_web_research(query, stemlab=False):
        assert query == "AI stem separation tools"
        assert stemlab is False
        return {
            "available": False,
            "query": query,
            "missing_configuration": "RESEARCH_PROVIDER is not configured",
            "next_setup_step": "Set RESEARCH_PROVIDER and RESEARCH_API_KEY.",
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "run_web_research", fake_run_web_research)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("web research AI stem separation tools", event_id="evt-web-research-unavailable"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("Live web research unavailable:")
    assert "requested query: AI stem separation tools" in captured["text"]
    assert "missing configuration: RESEARCH_PROVIDER is not configured" in captured["text"]
    assert "next setup step: Set RESEARCH_PROVIDER and RESEARCH_API_KEY." in captured["text"]
    assert captured["kwargs"] == {"unfurl_links": False, "unfurl_media": False}


def test_stemlab_live_web_research_command_returns_unavailable_without_provider(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {"ok": True, "ts": "123"}

    def fake_run_web_research(query, stemlab=False):
        assert query == "Ableton AI stem export complaints"
        assert stemlab is True
        return {
            "available": False,
            "query": query,
            "missing_configuration": "RESEARCH_API_KEY is not set",
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "run_web_research", fake_run_web_research)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "stemlab live web research Ableton AI stem export complaints",
            event_id="evt-stemlab-live-web-research-unavailable",
        ),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab live web research unavailable:")
    assert "requested query: Ableton AI stem export complaints" in captured["text"]
    assert "what Bishop would research:" in captured["text"]
    assert "missing configuration: RESEARCH_API_KEY is not set" in captured["text"]
    assert captured["kwargs"] == {"unfurl_links": False, "unfurl_media": False}


def test_web_research_command_formats_mocked_available_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {"ok": True, "ts": "123"}

    def fake_run_web_research(query, stemlab=False):
        assert query == "best stem separation APIs"
        assert stemlab is False
        return {
            "available": True,
            "query": query,
            "sources": [
                {
                    "title": "Source A",
                    "url": "https://example.com/source-a",
                    "snippet": "Source-backed snippet.",
                }
            ],
            "findings": ["Source A: Source-backed snippet."],
            "confidence": "medium",
            "repeated_patterns": ["No repeated deterministic theme appeared across at least 2 sources."],
            "evidence_quality": ["single-source claims need verification"],
            "suggested_next_queries": ["best stem separation APIs official documentation"],
            "open_questions": ["Which API performs best on dense EDM?"],
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "run_web_research", fake_run_web_research)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("web research best stem separation APIs", event_id="evt-web-research-available"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("Live web research result:")
    assert "Query: best stem separation APIs" in captured["text"]
    assert "Source A: Source-backed snippet." in captured["text"]
    assert "Source A - https://example.com/source-a" in captured["text"]
    assert "Repeated patterns:" in captured["text"]
    assert "Suggested next queries:" in captured["text"]
    assert "Confidence: medium" in captured["text"]
    assert captured["text"].index("Repeated patterns:") < captured["text"].index("Sources checked:")
    assert captured["text"].index("Evidence quality:") < captured["text"].index("Confidence: medium")
    assert captured["text"].index("Confidence: medium") < captured["text"].index("Product implications:")
    assert captured["kwargs"] == {"unfurl_links": False, "unfurl_media": False}


def test_web_research_response_escapes_external_slack_markup():
    text = slack_route.format_web_research_response(
        {
            "available": True,
            "query": "malicious provider text",
            "sources": [
                {
                    "title": "<!channel>",
                    "url": "https://example.com/?a=<@U123>&b=1",
                    "snippet": "ignored here",
                }
            ],
            "findings": ["<!channel> says use <@U123> & ship it"],
            "confidence": "medium",
            "open_questions": [],
        }
    )

    assert "<!channel>" not in text
    assert "<@U123>" not in text
    assert "&lt;!channel&gt;" in text
    assert "&lt;@U123&gt;" in text
    assert "&amp;" in text


def test_web_research_response_truncates_and_limits_slack_output():
    long_finding = "Long source: " + ("dense provider snippet " * 20)
    long_title = "Very long source title " + ("with extra words " * 10)
    intact_url = "https://example.com/source-with-intact-url"

    text = slack_route.format_web_research_response(
        {
            "available": True,
            "query": "compact output",
            "sources": [{"title": long_title, "url": intact_url, "snippet": "ignored"}],
            "findings": [
                long_finding,
                "Finding two",
                "Finding three",
                "Finding four should be hidden",
            ],
            "repeated_patterns": ["Pattern one", "Pattern two"],
            "evidence_quality": ["Quality one"],
            "product_implications": ["Implication one"],
            "open_questions": ["Question one?", "Question two?", "Question three should be hidden?"],
            "suggested_next_queries": ["Query one", "Query two", "Query three", "Query four hidden"],
        }
    )

    finding_line = next(line for line in text.splitlines() if line.startswith("* Long source:"))
    assert finding_line.endswith("...")
    assert len(finding_line) <= 224
    assert long_finding not in text
    assert "Finding four should be hidden" not in text
    assert "Question one?" in text
    assert "Question two?" in text
    assert "Question three should be hidden?" not in text
    assert "Query one" in text
    assert "Query two" in text
    assert "Query three" in text
    assert "Query four hidden" not in text
    source_line = next(line for line in text.splitlines() if intact_url in line)
    assert source_line.endswith(intact_url)
    assert "..." in source_line
    assert long_title not in text
    assert intact_url in text
    assert "Note: Slack may preview some source links." not in text


def test_web_research_response_unavailable_output_unchanged():
    text = slack_route.format_web_research_response(
        {
            "available": False,
            "query": "missing provider",
            "missing_configuration": "RESEARCH_PROVIDER is not configured",
            "next_setup_step": "Set RESEARCH_PROVIDER and RESEARCH_API_KEY.",
        }
    )

    assert text == (
        "Live web research unavailable:\n"
        "* requested query: missing provider\n"
        "* missing configuration: RESEARCH_PROVIDER is not configured\n"
        "* next setup step: Set RESEARCH_PROVIDER and RESEARCH_API_KEY."
    )


def test_stemlab_live_web_research_command_formats_mocked_available_result(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {"ok": True, "ts": "123"}

    def fake_run_web_research(query, stemlab=False):
        assert query == "AI stems Ableton workflow"
        assert stemlab is True
        return {
            "available": True,
            "query": query,
            "sources": [
                {
                    "title": "Producer workflow source",
                    "url": "https://example.com/workflow",
                    "snippet": "Workflow evidence.",
                }
            ],
            "findings": ["Producer workflow source: Workflow evidence."],
            "confidence": "medium",
            "repeated_patterns": ["No repeated deterministic theme appeared across at least 2 sources."],
            "evidence_quality": ["single-source claims need verification"],
            "weak_signals": ["No obvious weak signals from deterministic source checks."],
            "suggested_next_queries": ["AI stems Ableton workflow reddit complaints"],
            "product_implications": ["Focus on clean labels and Ableton-ready exports."],
            "open_questions": ["How often do producers reuse generated stems?"],
        }

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "run_web_research", fake_run_web_research)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "stemlab live web research AI stems Ableton workflow",
            event_id="evt-stemlab-web-research-available",
        ),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab live web research result:")
    assert "Weak signals:" in captured["text"]
    assert "Product implications:" in captured["text"]
    assert "What not to build:" in captured["text"]
    assert "Suggested next queries:" in captured["text"]
    assert "Producer workflow source - https://example.com/workflow" in captured["text"]
    assert captured["text"].index("Weak signals:") < captured["text"].index("Findings:")
    assert captured["kwargs"] == {"unfurl_links": False, "unfurl_media": False}


def test_research_command_does_not_trigger_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab source backed finding", event_id="evt-research-no-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab source-backed finding format:")
    assert captured["memories"] == []


def test_stemlab_research_command_does_not_trigger_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab research", event_id="evt-stemlab-research-no-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab research plan:")
    assert captured["memories"] == []


def test_stemlab_related_durable_message_is_captured_automatically(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "generate_reply",
        lambda user_id, message: (
            "Decision: StemLab should focus on Ableton-ready stem packs for the v0 workflow."
        ),
    )
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: False)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", lambda user_id, lane, limit=100: [])
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "For StemLab, decision: focus on producer-ready Ableton stem packs.",
            event_id="evt-stemlab-auto-memory",
        ),
    )

    assert response.status_code == 200
    assert captured["text"] == (
        "Decision: StemLab should focus on Ableton-ready stem packs for the v0 workflow."
    )
    assert captured["memories"]
    assert captured["memories"][0]["user_id"] == "U123"
    assert captured["memories"][0]["lane"] == "stemlab"
    assert captured["memories"][0]["visibility"] == "private"
    assert captured["memories"][0]["category"] == "StemLab Decision"
    assert captured["memories"][0]["content"] == (
        "Decision: focus on producer-ready Ableton stem packs."
    )


def test_stemlab_explicit_decision_memory_is_captured():
    items = slack_route.extract_stemlab_memory_items(
        "For StemLab, decision: validate separation-first before pure generation.",
        "Decision: StemLab should focus on Ableton-ready stem packs.",
    )

    assert items == [
        {
            "category": "StemLab Decision",
            "content": "Decision: validate separation-first before pure generation.",
        }
    ]


def test_stemlab_explicit_risk_memory_is_captured():
    items = slack_route.extract_stemlab_memory_items(
        "For StemLab, risk: separation quality may struggle on dense EDM mixes.",
        "",
    )

    assert items == [
        {
            "category": "StemLab Risk",
            "content": "Risk: separation quality may struggle on dense EDM mixes.",
        }
    ]


def test_multiple_explicit_stemlab_memories_in_one_message_are_cleanly_captured():
    items = slack_route.extract_stemlab_memory_items(
        (
            "For StemLab, decision: validate separation-first before pure generation. "
            "For StemLab, risk: separation quality may struggle on dense EDM mixes."
        ),
        "",
    )

    assert items == [
        {
            "category": "StemLab Decision",
            "content": "Decision: validate separation-first before pure generation.",
        },
        {
            "category": "StemLab Risk",
            "content": "Risk: separation quality may struggle on dense EDM mixes.",
        },
    ]


def test_stemlab_response_text_is_not_captured_without_explicit_user_memory():
    items = slack_route.extract_stemlab_memory_items(
        "What should we do next for StemLab?",
        "Decision: StemLab should focus on Ableton-ready stem packs.",
    )

    assert items == []


def test_generic_stemlab_discussion_is_not_captured_as_memory():
    items = slack_route.extract_stemlab_memory_items(
        "What should we do next for StemLab?",
        "",
    )

    assert items == []


def test_generic_message_is_not_captured_as_stemlab_memory(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "generate_reply",
        lambda user_id, message: "Decision: focus the website homepage on qualified leads.",
    )
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: False)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", lambda user_id, lane, limit=100: [])
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "Decision: focus the website homepage on qualified leads.",
            event_id="evt-generic-auto-memory",
        ),
    )

    assert response.status_code == 200
    assert captured["text"] == "Decision: focus the website homepage on qualified leads."
    assert captured["memories"] == []


def test_help_modes_and_status_commands_are_not_captured_as_stemlab_memory(monkeypatch):
    reset_route_state()
    captured = {"responses": [], "memories": []}

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", lambda user_id, lane, limit=20: [])
    monkeypatch.setattr(slack_route, "get_tasks", lambda user_id, lane=None, status="pending", limit=10: [])
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
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "stemlab")

    for index, command in enumerate(("help", "modes", "status"), start=1):
        response = client.post(
            "/slack/events",
            json=make_event(command, event_id=f"evt-no-stemlab-capture-{index}"),
        )
        assert response.status_code == 200

    assert len(captured["responses"]) == 3
    assert captured["memories"] == []


def test_duplicate_stemlab_memory_is_not_saved_twice(monkeypatch):
    reset_route_state()
    memory_store = [
        {
            "user_id": "U123",
            "owner_user_id": "U123",
            "lane": "stemlab",
            "visibility": "private",
            "category": "StemLab Decision",
            "content": "Decision: StemLab should focus on Ableton-ready stem packs.",
        }
    ]

    def fake_post_message(channel, text):
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        memory_store.append(kwargs)
        return {"id": len(memory_store), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "generate_reply",
        lambda user_id, message: "Decision: StemLab should focus on Ableton-ready stem packs.",
    )
    monkeypatch.setattr(slack_route, "response_contains_commitment", lambda response_text: False)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=100: [item for item in memory_store if item["lane"] == lane],
    )
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "For StemLab, decision: StemLab should focus on Ableton-ready stem packs.",
            event_id="evt-stemlab-duplicate-memory",
        ),
    )

    assert response.status_code == 200
    assert len(memory_store) == 1


def test_show_stemlab_memory_command(monkeypatch):
    reset_route_state()
    captured = {"calls": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_get_memories(user_id, lane, limit=100):
        captured["calls"].append((user_id, lane, limit))
        return [
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Decision",
                "content": "Decision: StemLab should focus on Ableton-ready stem packs.",
            },
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Risk",
                "content": "Risk: audio quality may not satisfy working producers.",
            },
        ]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("show stemlab memory", event_id="evt-show-stemlab-memory"),
    )

    assert response.status_code == 200
    assert captured["calls"] == [("U123", "stemlab", 100)]
    assert captured["text"].startswith("StemLab project memory:")
    assert "StemLab Decision:" in captured["text"]
    assert "Decision: StemLab should focus on Ableton-ready stem packs." in captured["text"]
    assert "StemLab Risk:" in captured["text"]
    assert "Risk: audio quality may not satisfy working producers." in captured["text"]


def test_stemlab_save_source_backed_finding_saves_and_shows_in_stemlab_memory(monkeypatch):
    reset_route_state()
    captured = {"responses": []}
    memory_store = []

    def fake_post_message(channel, text):
        captured["responses"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        memory_store.append(
            {
                "owner_user_id": kwargs["user_id"],
                "lane": kwargs["lane"],
                "visibility": kwargs["visibility"],
                "category": kwargs["category"],
                "content": kwargs["content"],
            }
        )
        return {"id": len(memory_store), **kwargs}

    def fake_get_memories(user_id, lane, limit=100):
        return [
            item
            for item in memory_store
            if item["owner_user_id"] == user_id and item["lane"] == lane
        ][:limit]

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_memories", fake_get_memories)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    finding = "Ableton users report stem separation can be slow on longer files"
    source = "https://www.reddit.com/r/ableton/comments/example"
    save_response = client.post(
        "/slack/events",
        json=make_event(
            f"stemlab save source backed finding {finding} source {source}",
            event_id="evt-save-source-backed-finding",
        ),
    )

    assert save_response.status_code == 200
    assert len(memory_store) == 1
    assert memory_store[0]["lane"] == "stemlab"
    assert memory_store[0]["category"] == "StemLab Research Finding"
    assert memory_store[0]["visibility"] == "private"
    assert memory_store[0]["content"] == (
        f"StemLab source-backed finding: {finding} Source: {source} Confidence: medium."
    )
    assert captured["responses"][-1] == (
        "Saved StemLab source-backed finding.\n\n"
        f"Finding:\n{finding}\n\n"
        f"Source:\n{source}\n\n"
        "Confidence:\nmedium"
    )

    show_response = client.post(
        "/slack/events",
        json=make_event("show stemlab memory", event_id="evt-show-saved-source-backed-finding"),
    )

    assert show_response.status_code == 200
    assert captured["responses"][-1].startswith("StemLab project memory:")
    assert "StemLab Research Finding:" in captured["responses"][-1]
    assert f"StemLab source-backed finding: {finding}" in captured["responses"][-1]
    assert f"Source: {source}" in captured["responses"][-1]
    assert "Confidence: medium." in captured["responses"][-1]


def test_stemlab_save_source_backed_finding_missing_source_does_not_save(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "stemlab save source backed finding Ableton users report slow stem separation",
            event_id="evt-save-source-backed-finding-missing-source",
        ),
    )

    assert response.status_code == 200
    assert captured["memories"] == []
    assert captured["text"].startswith("To save a StemLab source-backed finding, use:")
    assert "stemlab save source backed finding <finding text> source <url>" in captured["text"]
    assert "Example:" in captured["text"]


def test_stemlab_save_source_backed_finding_missing_finding_does_not_save(monkeypatch):
    reset_route_state()
    captured = {"memories": []}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_add_memory(**kwargs):
        captured["memories"].append(kwargs)
        return {"id": len(captured["memories"]), **kwargs}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event(
            "stemlab save source backed finding source https://www.reddit.com/r/ableton/comments/example",
            event_id="evt-save-source-backed-finding-missing-finding",
        ),
    )

    assert response.status_code == 200
    assert captured["memories"] == []
    assert captured["text"].startswith("To save a StemLab source-backed finding, use:")
    assert "stemlab save source backed finding <finding text> source <url>" in captured["text"]
    assert "Example:" in captured["text"]


def test_stemlab_memory_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=100: [
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Product Direction",
                "content": "Product direction: StemLab is producer-ready workflow software.",
            }
        ],
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab memory", event_id="evt-stemlab-memory"),
    )

    assert response.status_code == 200
    assert captured["text"].startswith("StemLab project memory:")
    assert "StemLab Product Direction:" in captured["text"]
    assert "Product direction: StemLab is producer-ready workflow software." in captured["text"]


def test_stemlab_decisions_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=100: [
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Decision",
                "content": "Decision: validate separation quality before generation.",
            },
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Risk",
                "content": "Risk: unclear licensing.",
            },
        ],
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab decisions", event_id="evt-stemlab-decisions"),
    )

    assert response.status_code == 200
    assert captured["text"] == (
        "StemLab Decision:\n"
        "* Decision: validate separation quality before generation."
    )


def test_stemlab_open_questions_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=100: [
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Open Question",
                "content": "Question: should v0 create stems or separate uploads?",
            }
        ],
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab open questions", event_id="evt-stemlab-open-questions"),
    )

    assert response.status_code == 200
    assert captured["text"] == (
        "StemLab Open Question:\n"
        "* Question: should v0 create stems or separate uploads?"
    )


def test_stemlab_risks_command(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=100: [
            {
                "owner_user_id": user_id,
                "lane": "stemlab",
                "visibility": "private",
                "category": "StemLab Risk",
                "content": "Risk: Ableton export quality may be hard to automate.",
            }
        ],
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("stemlab risks", event_id="evt-stemlab-risks"),
    )

    assert response.status_code == 200
    assert captured["text"] == (
        "StemLab Risk:\n"
        "* Risk: Ableton export quality may be hard to automate."
    )


def test_mode_cmo_returns_strategic_acknowledgement(monkeypatch):
    reset_route_state()
    captured = {}
    set_mode_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        set_mode_calls.append((user_id, mode))
        return mode

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode cmo", event_id="evt-mode-cmo")
    )

    assert response.status_code == 200
    assert set_mode_calls == [("U123", "cmo")]
    assert captured["text"] == (
        "CMO mode active.\n"
        "I’ll diagnose the business or creative constraint first, then think in terms of revenue, "
        "audience, offer, channel, creative, production reality, and measurable next action."
    )


def test_mode_creative_returns_creative_acknowledgement(monkeypatch):
    reset_route_state()
    captured = {}
    set_mode_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        set_mode_calls.append((user_id, mode))
        return mode

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode creative", event_id="evt-mode-creative")
    )

    assert response.status_code == 200
    assert set_mode_calls == [("U123", "creative")]
    assert captured["text"] == (
        "Creative mode active.\n"
        "I’ll diagnose before concepting, then focus on TV, social, retail, paid creative, "
        "campaign spines, scripts, AI video prompts, production feasibility, and testable next moves."
    )


def test_mode_concept_alias_routes_to_creative(monkeypatch):
    reset_route_state()
    captured = {}
    set_mode_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        set_mode_calls.append((user_id, mode))
        return mode

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode concept lab", event_id="evt-mode-concept-lab")
    )

    assert response.status_code == 200
    assert set_mode_calls == [("U123", "creative")]
    assert captured["text"].startswith("Creative mode active.")


def test_mode_stemlab_returns_music_product_acknowledgement(monkeypatch):
    reset_route_state()
    captured = {}
    set_mode_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        set_mode_calls.append((user_id, mode))
        return mode

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode stemlab", event_id="evt-mode-stemlab")
    )

    assert response.status_code == 200
    assert set_mode_calls == [("U123", "stemlab")]
    assert captured["text"] == (
        "StemLab mode active.\n"
        "I’ll think like a music-tech founder, EDM producer, DJ, product strategist, "
        "and workflow designer. I’ll focus on usable stems, DJ-ready arrangements, "
        "Ableton workflows, prompt strategy, competitive gaps, MVP definition, "
        "and practical next actions."
    )


def test_mode_product_returns_product_acknowledgement(monkeypatch):
    reset_route_state()
    captured = {}
    set_mode_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        set_mode_calls.append((user_id, mode))
        return mode

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode product", event_id="evt-mode-product")
    )

    assert response.status_code == 200
    assert set_mode_calls == [("U123", "product")]
    assert captured["text"] == (
        "Product mode active.\n"
        "I’ll think like a product strategist, founder, operator, and practical builder. "
        "I’ll focus on user pain, MVP scope, positioning, workflows, monetization, "
        "test plans, tradeoffs, and the next useful decision."
    )


def test_mode_default_still_returns_plain_acknowledgement(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_mode", lambda user_id, mode: mode)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode default", event_id="evt-mode-default")
    )

    assert response.status_code == 200
    assert captured["text"] == "Mode set to default."


def test_unknown_mode_listing_includes_cmo(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events", json=make_event("mode bogus", event_id="evt-mode-bogus")
    )

    assert response.status_code == 200
    text = captured["text"]
    assert text.startswith("Unknown mode. Available modes:")
    assert "cmo" in text
    assert "creative" in text
    assert "default" in text
    assert "work" in text
    assert "personal" in text
    assert "website" in text
    assert "stemlab" in text
    assert "product" in text


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


def test_focus_stemlab_sets_focus_for_user_and_lane(monkeypatch):
    reset_route_state()
    captured = {}
    set_focus_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_active_focus(user_id, lane, focus):
        set_focus_calls.append((user_id, lane, focus))
        return focus

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_active_focus", fake_set_active_focus)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("focus stemlab", event_id="evt-focus-stemlab"),
    )

    assert response.status_code == 200
    assert set_focus_calls == [("U123", "work", "stemlab")]
    assert captured["text"] == "StemLab is now the focus here."


def test_switch_focus_to_stemlab_sets_focus(monkeypatch):
    reset_route_state()
    captured = {}
    set_focus_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_active_focus(user_id, lane, focus):
        set_focus_calls.append((user_id, lane, focus))
        return focus

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_active_focus", fake_set_active_focus)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "dj")

    response = client.post(
        "/slack/events",
        json=make_event("switch focus to stemlab", event_id="evt-switch-focus-stemlab"),
    )

    assert response.status_code == 200
    assert set_focus_calls == [("U123", "dj", "stemlab")]
    assert captured["text"] == "StemLab is now the focus here."


def test_show_current_focus(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "stemlab")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("current focus", event_id="evt-current-focus"),
    )

    assert response.status_code == 200
    assert captured["text"] == "Current focus here is StemLab."


def test_show_current_focus_when_none(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("current focus", event_id="evt-current-focus-none"),
    )

    assert response.status_code == 200
    assert captured["text"] == "No active focus here."


def test_clear_focus(monkeypatch):
    reset_route_state()
    captured = {}
    clear_focus_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_clear_active_focus(user_id, lane):
        clear_focus_calls.append((user_id, lane))
        return True

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_active_focus", fake_clear_active_focus)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("clear focus", event_id="evt-clear-focus"),
    )

    assert response.status_code == 200
    assert clear_focus_calls == [("U123", "work")]
    assert captured["text"] == "Focus cleared here."


def test_natural_focus_phrases_set_focus(monkeypatch):
    reset_route_state()
    posted = []
    set_focus_calls = []
    memory_calls = []

    def fake_post_message(channel, text):
        posted.append(text)
        return {"ok": True, "ts": "123"}

    def fake_set_active_focus(user_id, lane, focus):
        set_focus_calls.append((user_id, lane, focus))
        return focus

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_active_focus", fake_set_active_focus)
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    cases = [
        ("let’s work on StemLab for a bit", "stemlab", "StemLab is now the focus here."),
        ("back to Bishop", "bishop", "Bishop is now the focus here."),
        ("switch us over to DJ stuff", "dj", "DJ is now the focus here."),
        ("let’s talk website", "website", "Website is now the focus here."),
    ]

    for index, (message, focus, response_text) in enumerate(cases):
        response = client.post(
            "/slack/events",
            json=make_event(message, event_id=f"evt-natural-focus-{index}"),
        )

        assert response.status_code == 200
        assert set_focus_calls[-1] == ("U123", "work", focus)
        assert posted[-1] == response_text

    assert memory_calls == []


def test_natural_clear_focus_phrase_clears_focus(monkeypatch):
    reset_route_state()
    captured = {}
    clear_focus_calls = []
    memory_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_clear_active_focus(user_id, lane):
        clear_focus_calls.append((user_id, lane))
        return True

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "clear_active_focus", fake_clear_active_focus)
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("clear the focus for now", event_id="evt-natural-clear-focus"),
    )

    assert response.status_code == 200
    assert clear_focus_calls == [("U123", "work")]
    assert captured["text"] == "Focus cleared here."
    assert memory_calls == []


def test_natural_focus_safety_cases_do_not_change_focus(monkeypatch):
    reset_route_state()
    posted = []
    set_focus_calls = []
    clear_focus_calls = []
    memory_calls = []

    def fake_post_message(channel, text):
        posted.append(text)
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "set_active_focus",
        lambda user_id, lane, focus: set_focus_calls.append((user_id, lane, focus)),
    )
    monkeypatch.setattr(
        slack_route,
        "clear_active_focus",
        lambda user_id, lane: clear_focus_calls.append((user_id, lane)),
    )
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "generate_reply", lambda user_id, message: "General reply.")
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    cases = [
        "what should we research next?",
        "tell me about websites",
        "what DJ software should I use?",
        "let’s work on this",
    ]

    for index, message in enumerate(cases):
        response = client.post(
            "/slack/events",
            json=make_event(message, event_id=f"evt-natural-focus-safety-{index}"),
        )
        assert response.status_code == 200
        assert posted[-1] == "General reply."

    assert set_focus_calls == []
    assert clear_focus_calls == []
    assert memory_calls == []


def test_natural_focus_remains_user_and_lane_scoped(monkeypatch):
    reset_route_state()
    set_focus_calls = []

    def fake_set_active_focus(user_id, lane, focus):
        set_focus_calls.append((user_id, lane, focus))
        return focus

    def fake_get_lane_from_channel(channel_id, resolver=None):
        return {"CWORK": "work", "CDJ": "dj"}[channel_id]

    monkeypatch.setattr(slack_route, "post_message", lambda channel, text: {"ok": True, "ts": "123"})
    monkeypatch.setattr(slack_route, "set_active_focus", fake_set_active_focus)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", fake_get_lane_from_channel)

    first = client.post(
        "/slack/events",
        json=make_event(
            "let’s work on StemLab for a bit",
            event_id="evt-natural-focus-user-lane-1",
            user_id="U123",
            channel_id="CWORK",
        ),
    )
    second = client.post(
        "/slack/events",
        json=make_event(
            "back to Bishop",
            event_id="evt-natural-focus-user-lane-2",
            user_id="U999",
            channel_id="CDJ",
        ),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert set_focus_calls == [
        ("U123", "work", "stemlab"),
        ("U999", "dj", "bishop"),
    ]


def test_unsupported_focus_returns_helpful_response(monkeypatch):
    reset_route_state()
    captured = {}
    set_focus_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(
        slack_route,
        "set_active_focus",
        lambda user_id, lane, focus: set_focus_calls.append((user_id, lane, focus)),
    )
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("focus finance", event_id="evt-focus-unsupported"),
    )

    assert response.status_code == 200
    assert set_focus_calls == []
    assert captured["text"].startswith("Unsupported focus: finance.")
    assert "stemlab" in captured["text"]
    assert "website" in captured["text"]


def test_focus_does_not_change_mode_or_provider_status(monkeypatch):
    reset_route_state()
    captured = {}
    mode_calls = []
    provider_calls = []

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_set_mode(user_id, mode):
        mode_calls.append((user_id, mode))

    def fake_set_provider_override(provider):
        provider_calls.append(provider)

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "set_active_focus", lambda user_id, lane, focus: focus)
    monkeypatch.setattr(slack_route, "set_mode", fake_set_mode)
    monkeypatch.setattr(slack_route, "set_provider_override", fake_set_provider_override)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post(
        "/slack/events",
        json=make_event("set focus stemlab", event_id="evt-focus-no-mode-provider"),
    )

    assert response.status_code == 200
    assert mode_calls == []
    assert provider_calls == []
    assert captured["text"] == "StemLab is now the focus here."


def test_stemlab_focus_influences_general_question_without_memory_capture(monkeypatch):
    reset_route_state()
    captured = {"posted": []}
    memory_calls = []

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Research next: validate Ableton-ready stem-pack pain with producers."

    def fake_add_memory(**kwargs):
        memory_calls.append(kwargs)
        return {"id": 1}

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "stemlab")
    monkeypatch.setattr(slack_route, "add_memory", fake_add_memory)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event(
            "what should we research next?",
            event_id="evt-stemlab-focus-general-question",
        ),
    )

    assert response.status_code == 200
    assert captured["message_to_model"].startswith("Slack style:")
    assert "answer naturally and concisely" in captured["message_to_model"]
    assert "For simple questions, use 1 to 4 short paragraphs or bullets" in captured["message_to_model"]
    assert "prefer one recommendation, up to 3 priorities, and one clear next move" in captured["message_to_model"]
    assert "Active focus: StemLab." in captured["message_to_model"]
    assert "Use StemLab context only when the current user message is ambiguous." in captured["message_to_model"]
    assert "Active focus is guidance only for ambiguous messages." in captured["message_to_model"]
    assert "current user message is the source of truth for topic" in captured["message_to_model"]
    assert "Do not redirect RTG, Rooms To Go, retail, TV, social, or campaign prompts into StemLab" in captured["message_to_model"]
    assert "Focused Slack answer shape: start with one direct recommendation." in captured["message_to_model"]
    assert "Use at most 2 or 3 short bullets." in captured["message_to_model"]
    assert "End with one concrete next move." in captured["message_to_model"]
    assert "Avoid nested bullets unless the user explicitly asks for detail." in captured["message_to_model"]
    assert "Do not end with generic requests for more context" in captured["message_to_model"]
    assert "what should we research next?" in captured["message_to_model"]
    assert captured["posted"][-1] == "Research next: validate Ableton-ready stem-pack pain with producers."
    assert memory_calls == []


def test_stemlab_focus_frames_context_as_ambiguous_guidance_for_explicit_rtg_prompt(monkeypatch):
    reset_route_state()
    captured = {"posted": []}

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Use the RTG July 4 campaign as the topic."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "stemlab")
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "creative")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event(
            "Give me RTG July 4 creative TV and social ideas.",
            event_id="evt-stemlab-focus-explicit-rtg",
        ),
    )

    assert response.status_code == 200
    assert "Active focus: StemLab." in captured["message_to_model"]
    assert "Active focus is guidance only for ambiguous messages." in captured["message_to_model"]
    assert "If the user explicitly names a brand, project, campaign, domain, or subject, answer that subject." in captured["message_to_model"]
    assert "Do not redirect RTG, Rooms To Go, retail, TV, social, or campaign prompts into StemLab" in captured["message_to_model"]
    assert "Give me RTG July 4 creative TV and social ideas." in captured["message_to_model"]
    assert captured["posted"] == ["Use the RTG July 4 campaign as the topic."]


def test_bishop_focus_guides_general_question_to_model_without_side_effects(monkeypatch):
    reset_route_state()
    captured = {"posted": []}
    get_focus_calls = []
    memory_calls = []
    task_calls = []

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Clean up the Slack focus tests next."

    def fake_get_active_focus(user_id, lane):
        get_focus_calls.append((user_id, lane))
        return "bishop"

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", fake_get_active_focus)
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "add_task_for_lane", lambda **kwargs: task_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("what should we clean up next?", event_id="evt-bishop-focus-general"),
    )

    assert response.status_code == 200
    assert get_focus_calls == [("U123", "work")]
    assert captured["message_to_model"].startswith("Slack style:")
    assert "Active focus: Bishop." in captured["message_to_model"]
    assert (
        "Interpret ambiguous follow-ups through Bishop project, repo, product, "
        "config, Slack route, tests, deploy, and ops context."
    ) in captured["message_to_model"]
    assert (
        "Give concrete Bishop next steps. Do not give generic productivity, "
        "project-management, or decision-framework advice."
    ) in captured["message_to_model"]
    assert "Focused Slack answer shape: start with one direct recommendation." in captured["message_to_model"]
    assert "Use at most 2 or 3 short bullets." in captured["message_to_model"]
    assert "End with one concrete next move." in captured["message_to_model"]
    assert "Avoid nested bullets unless the user explicitly asks for detail." in captured["message_to_model"]
    assert "Do not end with generic requests for more context" in captured["message_to_model"]
    assert "what should we clean up next?" in captured["message_to_model"]
    assert captured["posted"] == ["Clean up the Slack focus tests next."]
    assert memory_calls == []
    assert task_calls == []


def test_dj_focus_guides_general_question_to_model_without_side_effects(monkeypatch):
    reset_route_state()
    captured = {"posted": []}
    memory_calls = []
    task_calls = []

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Prep the first transition block."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "dj")
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "add_task_for_lane", lambda **kwargs: task_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "dj")

    response = client.post(
        "/slack/events",
        json=make_event("what should I prep next?", event_id="evt-dj-focus-general"),
    )

    assert response.status_code == 200
    assert captured["message_to_model"].startswith("Slack style:")
    assert "Active focus: DJ." in captured["message_to_model"]
    assert (
        "Interpret ambiguous follow-ups through DJ, music, set prep, tracks, "
        "transitions, crates, events, mixes, and creative workflow context."
    ) in captured["message_to_model"]
    assert (
        "Give concrete DJ next steps. Do not give generic project, meeting, "
        "or decision-prep advice."
    ) in captured["message_to_model"]
    assert "Focused Slack answer shape: start with one direct recommendation." in captured["message_to_model"]
    assert "Use at most 2 or 3 short bullets." in captured["message_to_model"]
    assert "End with one concrete next move." in captured["message_to_model"]
    assert "Avoid nested bullets unless the user explicitly asks for detail." in captured["message_to_model"]
    assert "Do not end with generic requests for more context" in captured["message_to_model"]
    assert "what should I prep next?" in captured["message_to_model"]
    assert captured["posted"] == ["Prep the first transition block."]
    assert memory_calls == []
    assert task_calls == []


def test_website_focus_guides_general_question_to_model_without_side_effects(monkeypatch):
    reset_route_state()
    captured = {"posted": []}
    memory_calls = []
    task_calls = []

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Improve the homepage proof section."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: "website")
    monkeypatch.setattr(slack_route, "add_memory", lambda **kwargs: memory_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "add_task_for_lane", lambda **kwargs: task_calls.append(kwargs))
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "website")

    response = client.post(
        "/slack/events",
        json=make_event("what should we improve next?", event_id="evt-website-focus-general"),
    )

    assert response.status_code == 200
    assert captured["message_to_model"].startswith("Slack style:")
    assert "Active focus: Website." in captured["message_to_model"]
    assert (
        "Interpret ambiguous follow-ups through website, content, pages, "
        "site structure, conversion, SEO, and product presence context."
    ) in captured["message_to_model"]
    assert (
        "Give concrete website next steps. Do not give generic productivity "
        "or product-management advice."
    ) in captured["message_to_model"]
    assert "Focused Slack answer shape: start with one direct recommendation." in captured["message_to_model"]
    assert "Use at most 2 or 3 short bullets." in captured["message_to_model"]
    assert "End with one concrete next move." in captured["message_to_model"]
    assert "Avoid nested bullets unless the user explicitly asks for detail." in captured["message_to_model"]
    assert "Do not end with generic requests for more context" in captured["message_to_model"]
    assert "what should we improve next?" in captured["message_to_model"]
    assert captured["posted"] == ["Improve the homepage proof section."]
    assert memory_calls == []
    assert task_calls == []


def test_no_active_focus_leaves_general_question_without_focus_context(monkeypatch):
    reset_route_state()
    captured = {"posted": []}

    def fake_post_message(channel, text):
        captured["posted"].append(text)
        return {"ok": True, "ts": "123"}

    def fake_generate_reply(user_id, message):
        captured["message_to_model"] = message
        return "Use the normal path."

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fake_generate_reply)
    monkeypatch.setattr(slack_route, "get_active_focus", lambda user_id, lane: None)
    monkeypatch.setattr(slack_route, "get_effective_provider", lambda: "openai")
    monkeypatch.setattr(slack_route, "get_provider_model", lambda provider=None: "gpt-4.1-mini")
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)
    monkeypatch.setattr(slack_route, "get_lane_from_channel", lambda channel_id, resolver=None: "work")

    response = client.post(
        "/slack/events",
        json=make_event("what should we work on next?", event_id="evt-no-focus-general"),
    )

    assert response.status_code == 200
    assert captured["message_to_model"].startswith("Slack style:")
    assert "Active focus:" not in captured["message_to_model"]
    assert "Focused Slack answer shape:" not in captured["message_to_model"]
    assert "Use at most 2 or 3 short bullets." not in captured["message_to_model"]
    assert "User message:\nwhat should we work on next?" in captured["message_to_model"]
    assert captured["posted"] == ["Use the normal path."]


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


@pytest.mark.parametrize(
    ("command", "event_id"),
    [
        ("build status", "evt-build-status"),
        ("project status", "evt-project-status"),
        ("bishop status", "evt-bishop-status"),
        ("bishop build status", "evt-bishop-build-status"),
        ("what is the build status", "evt-what-is-build-status"),
        ("where are we with bishop", "evt-where-are-we-bishop"),
        ("what did we just finish", "evt-what-did-we-finish"),
    ],
)
def test_build_project_status_commands_return_static_summary_without_side_effects(
    monkeypatch,
    command,
    event_id,
):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fail_generate_reply(user_id, message):
        raise AssertionError("build status must not call model generation")

    def fail_add_memory(**kwargs):
        raise AssertionError("build status must not save memory")

    def fail_add_task(**kwargs):
        raise AssertionError("build status must not create tasks")

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route, "add_memory", fail_add_memory)
    monkeypatch.setattr(slack_route, "add_task", fail_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event(command, event_id=event_id))

    assert response.status_code == 200
    assert captured["text"] == slack_route.bishop_build_status_text()
    assert captured["text"].startswith("Bishop Build Status")
    assert "Bishop v1 is effectively wrapped." in captured["text"]
    assert "Codex builds, tests, and summarizes" in captured["text"]
    assert "Use Bishop live for a few days and collect rough edges." in captured["text"]
    assert "Final runbook/status cleanup" not in captured["text"]


@pytest.mark.parametrize(
    ("command", "event_id"),
    [
        ("next sprint", "evt-next-sprint"),
        ("what should we build next", "evt-what-build-next"),
        ("what should we work on next", "evt-what-work-next"),
        ("recommend next sprint", "evt-recommend-next-sprint"),
        ("bishop next sprint", "evt-bishop-next-sprint"),
    ],
)
def test_next_sprint_commands_return_static_recommendation_without_side_effects(
    monkeypatch,
    command,
    event_id,
):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fail_generate_reply(user_id, message):
        raise AssertionError("next sprint must not call model generation")

    def fail_add_memory(**kwargs):
        raise AssertionError("next sprint must not save memory")

    def fail_add_task(**kwargs):
        raise AssertionError("next sprint must not create tasks")

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "generate_reply", fail_generate_reply)
    monkeypatch.setattr(slack_route, "add_memory", fail_add_memory)
    monkeypatch.setattr(slack_route, "add_task", fail_add_task)
    monkeypatch.setattr(slack_route, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event(command, event_id=event_id))

    assert response.status_code == 200
    assert captured["text"] == slack_route.bishop_next_sprint_text()
    assert captured["text"].startswith("Recommended Next Sprint")
    assert "Use Bishop live for a few days and collect rough edges." in captured["text"]
    assert "future response contract consolidation" in captured["text"]
    assert "Final runbook/status cleanup" not in captured["text"]
    assert "No commit/push unless Matt approves." in captured["text"]


def test_status_command_still_uses_existing_system_status(monkeypatch):
    reset_route_state()
    captured = {}

    def fake_post_message(channel, text):
        captured["text"] = text
        return {"ok": True, "ts": "123"}

    def fake_build_status_text(user_id, lane):
        return "*Bishop Status*\n\n*Mode:* default", "gpt-test"

    monkeypatch.setattr(slack_route, "post_message", fake_post_message)
    monkeypatch.setattr(slack_route, "build_status_text", fake_build_status_text)
    monkeypatch.setattr(slack_route, "log_conversation", lambda **kwargs: None)

    response = client.post("/slack/events", json=make_event("status", event_id="evt-system-status"))

    assert response.status_code == 200
    assert captured["text"].startswith("*Bishop Status*")
    assert "Bishop Build Status" not in captured["text"]


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
