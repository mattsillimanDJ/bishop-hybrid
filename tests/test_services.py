import pytest

from app.services import chat_service, task_service


@pytest.fixture(autouse=True)
def use_temp_task_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(task_service, "DB_PATH", test_db_path)


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


def test_get_mode_system_prompt_cmo_contains_lens_and_keywords():
    prompt = chat_service.get_mode_system_prompt("cmo")

    assert "CMO mode" in prompt
    for keyword in [
        "audience",
        "positioning",
        "offer",
        "channel",
        "creative",
        "budget",
        "measurable next action",
    ]:
        assert keyword in prompt, f"missing CMO lens keyword: {keyword}"

    assert "Do not over-format unless the user asks for a plan." in prompt


def test_get_mode_system_prompt_default_does_not_contain_cmo_lens():
    prompt = chat_service.get_mode_system_prompt("default")

    assert "CMO mode" not in prompt
    assert "audience, positioning, offer" not in prompt


def test_generate_reply_in_cmo_mode_passes_cmo_lens_to_model(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "cmo")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "strategic reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(
        user_id="U123",
        message="How should we launch the new event series?",
    )

    assert result == "strategic reply"
    assert "CMO mode" in captured["system_prompt"]
    assert "audience" in captured["system_prompt"]
    assert "positioning" in captured["system_prompt"]
    assert "measurable next action" in captured["system_prompt"]
    assert "How should we launch the new event series?" in captured["user_prompt"]


def test_generate_reply_in_default_mode_does_not_include_cmo_lens(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        return "default reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    chat_service.generate_reply(user_id="U123", message="What's a good dinner idea?")

    assert "CMO mode" not in captured["system_prompt"]
    assert "audience, positioning, offer" not in captured["system_prompt"]


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


def test_add_task_creates_pending_task():
    result = task_service.add_task(
        user_id="U123",
        channel_id="C123",
        session_id="C123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert result["created"] is True
    assert result["deduped"] is False
    assert result["status"] == "pending"
    assert result["task_text"] == "review the deck"

    tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(tasks) == 1
    assert tasks[0]["task_text"] == "review the deck"


def test_add_task_dedupes_matching_pending_task():
    first = task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        source_message="add task Review the deck!!!",
        task_text="Review the deck!!!",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["deduped"] is True
    assert second["task_text"] == "review the deck"

    tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(tasks) == 1


def test_mark_task_done_marks_matching_pending_task_done():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        task_text="Send the invoice!!!",
    )

    assert result["updated"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    done_tasks = task_service.get_tasks(user_id="U123", status="done")

    assert pending_tasks == []
    assert len(done_tasks) == 1
    assert done_tasks[0]["task_text"] == "send the invoice"
    assert done_tasks[0]["status"] == "done"


def test_mark_task_done_returns_false_when_no_pending_match():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        task_text="review the deck",
    )

    assert result["updated"] is False
    assert result["task"] is None

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(pending_tasks) == 1
    assert pending_tasks[0]["task_text"] == "send the invoice"


def test_remove_task_deletes_matching_pending_task():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        task_text="Review the deck!!!",
        status="pending",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "review the deck"
    assert result["task"]["status"] == "pending"

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert pending_tasks == []


def test_remove_task_returns_false_when_no_pending_match():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        task_text="send the invoice",
        status="pending",
    )

    assert result["deleted"] is False
    assert result["task"] is None

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(pending_tasks) == 1
    assert pending_tasks[0]["task_text"] == "review the deck"


def test_remove_task_can_delete_done_task_when_status_is_done():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.mark_task_done(user_id="U123", task_text="send the invoice")

    result = task_service.remove_task(
        user_id="U123",
        task_text="send the invoice",
        status="done",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    done_tasks = task_service.get_tasks(user_id="U123", status="done")
    assert done_tasks == []


def test_clear_tasks_deletes_only_requested_status():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.mark_task_done(user_id="U123", task_text="send the invoice")

    result = task_service.clear_tasks(user_id="U123", status="pending")

    assert result["deleted"] == 1
    assert task_service.get_tasks(user_id="U123", status="pending") == []

    done_tasks = task_service.get_tasks(user_id="U123", status="done")
    assert len(done_tasks) == 1
    assert done_tasks[0]["task_text"] == "send the invoice"


def test_add_task_same_text_can_exist_in_multiple_lanes():
    first = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is True
    assert first["deduped"] is False
    assert second["deduped"] is False

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1
    assert work_tasks[0]["task_text"] == "review the deck"
    assert dj_tasks[0]["task_text"] == "review the deck"


def test_add_task_dedupes_only_within_same_lane():
    first = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task Review the deck!!!",
        task_text="Review the deck!!!",
        assistant_commitment="Saved as a pending task.",
    )

    third = task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["deduped"] is True
    assert third["created"] is True
    assert third["deduped"] is False

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1


def test_mark_task_done_only_updates_matching_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        lane="work",
        task_text="Send the invoice!!!",
    )

    assert result["updated"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    work_done = task_service.get_tasks(user_id="U123", lane="work", status="done")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")
    dj_done = task_service.get_tasks(user_id="U123", lane="dj", status="done")

    assert work_pending == []
    assert len(work_done) == 1
    assert len(dj_pending) == 1
    assert dj_done == []


def test_remove_task_only_deletes_matching_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        lane="work",
        task_text="Review the deck!!!",
        status="pending",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "review the deck"

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert work_pending == []
    assert len(dj_pending) == 1
    assert dj_pending[0]["task_text"] == "review the deck"


def test_clear_tasks_only_clears_requested_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.clear_tasks(user_id="U123", lane="work", status="pending")

    assert result["deleted"] == 1

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert work_pending == []
    assert len(dj_pending) == 1
    assert dj_pending[0]["task_text"] == "send the invoice"


def test_get_tasks_returns_only_requested_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1
    assert work_tasks[0]["task_text"] == "review the deck"
    assert dj_tasks[0]["task_text"] == "send the invoice"
