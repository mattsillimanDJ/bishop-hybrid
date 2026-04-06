import pytest

from app.services import chat_service, task_service


def test_response_contains_commitment_true():
    assert chat_service.response_contains_commitment("On it. I'll proceed with that.") is True


def test_response_contains_commitment_false():
    assert chat_service.response_contains_commitment("Here is the completed draft.") is False


def test_generate_reply_uses_effective_provider(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(chat_service, "generate_memory_context", lambda user_id, message: "Ben is Matt's son")
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "- Do 1, 2, and 3")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "claude")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["provider"] = provider
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "test reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(user_id="U123", message="Tell me about Ben")

    assert result == "test reply"
    assert captured["provider"] == "claude"
    assert "work mode" in captured["system_prompt"]
    assert "Do 1, 2, and 3" in captured["user_prompt"]
    assert "Ben is Matt's son" in captured["user_prompt"]
    assert "Tell me about Ben" in captured["user_prompt"]


def test_looks_like_explicit_task_command():
    assert task_service.looks_like_explicit_task_command("add task review the deck") is True
    assert task_service.looks_like_explicit_task_command("save task call John") is True
    assert task_service.looks_like_explicit_task_command("add this to my list pick up dry cleaning") is True
    assert task_service.looks_like_explicit_task_command("hello bishop") is False


def test_extract_task_text_from_explicit_command():
    assert task_service.extract_task_text_from_explicit_command("add task review the deck") == "review the deck"
    assert task_service.extract_task_text_from_explicit_command("save task call John") == "call John"
    assert (
        task_service.extract_task_text_from_explicit_command(
            "add this to my list pick up dry cleaning"
        )
        == "pick up dry cleaning"
    )


def test_looks_like_reminder_request():
    assert task_service.looks_like_reminder_request("remind me tomorrow to review the deck") is True
    assert task_service.looks_like_reminder_request("please remind me next week to send the invoice") is True
    assert task_service.looks_like_reminder_request("could you remind me to call John") is True
    assert task_service.looks_like_reminder_request("what mode are you in") is False


def test_extract_task_text_from_reminder_request():
    assert (
        task_service.extract_task_text_from_reminder_request(
            "remind me tomorrow to review the deck"
        )
        == "review the deck"
    )
    assert (
        task_service.extract_task_text_from_reminder_request(
            "please remind me next week to send the invoice"
        )
        == "send the invoice"
    )
    assert (
        task_service.extract_task_text_from_reminder_request(
            "could you remind me to call John"
        )
        == "call John"
    )


def test_should_capture_task_from_user_message():
    assert task_service.should_capture_task_from_user_message("add task review the deck") is True
    assert task_service.should_capture_task_from_user_message("remind me tomorrow to review the deck") is True
    assert task_service.should_capture_task_from_user_message("hello bishop") is False


def test_build_task_text_from_user_message():
    assert task_service.build_task_text_from_user_message("add task review the deck") == "review the deck"
    assert (
        task_service.build_task_text_from_user_message("remind me tomorrow to review the deck")
        == "review the deck"
    )


def test_add_task_rejects_empty_task_text():
    with pytest.raises(ValueError):
        task_service.add_task(
            user_id="U123",
            source_message="add task",
            task_text="",
            assistant_commitment="Saved as a task.",
        )
