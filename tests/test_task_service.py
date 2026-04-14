from pathlib import Path

import pytest

from app.services import task_service


@pytest.fixture()
def isolated_task_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_bishop_memory.db"
    monkeypatch.setattr(task_service, "DB_PATH", db_path)
    return db_path


def test_normalize_task_text_strips_case_spacing_and_punctuation(isolated_task_db: Path):
    result = task_service.normalize_task_text("  Review   the deck!!  ")

    assert result == "review the deck"


def test_build_task_text_from_explicit_command(isolated_task_db: Path):
    result = task_service.build_task_text_from_user_message(
        "add task:   Review the deck tonight!! "
    )

    assert result == "Review the deck tonight"


def test_build_task_text_from_reminder_request(isolated_task_db: Path):
    result = task_service.build_task_text_from_user_message(
        "please remind me to send the invoice tomorrow."
    )

    assert result == "send the invoice tomorrow"


def test_add_task_dedupes_same_user_lane_and_normalized_text(isolated_task_db: Path):
    first = task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="Review the deck",
        assistant_commitment="Saved as a pending task.",
        lane="work",
        channel_id="C123",
        session_id="S123",
    )

    second = task_service.add_task(
        user_id="U123",
        source_message="add task   review the deck!!!",
        task_text=" review   the deck!!! ",
        assistant_commitment="Saved as a pending task.",
        lane="work",
        channel_id="C123",
        session_id="S123",
    )

    pending_tasks = task_service.get_tasks(
        user_id="U123",
        lane="work",
        status="pending",
        limit=10,
    )

    assert first["created"] is True
    assert first["deduped"] is False

    assert second["created"] is False
    assert second["deduped"] is True
    assert second["id"] == first["id"]

    assert len(pending_tasks) == 1
    assert pending_tasks[0]["task_text"] == "Review the deck"


def test_add_task_allows_same_text_in_different_lanes(isolated_task_db: Path):
    work_task = task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="Review the deck",
        assistant_commitment="Saved as a pending task.",
        lane="work",
    )

    dj_task = task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="Review the deck",
        assistant_commitment="Saved as a pending task.",
        lane="dj",
    )

    work_tasks = task_service.get_tasks(
        user_id="U123",
        lane="work",
        status="pending",
        limit=10,
    )
    dj_tasks = task_service.get_tasks(
        user_id="U123",
        lane="dj",
        status="pending",
        limit=10,
    )

    assert work_task["created"] is True
    assert dj_task["created"] is True
    assert work_task["id"] != dj_task["id"]

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1


def test_mark_task_done_updates_matching_pending_task(isolated_task_db: Path):
    created = task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="Send the invoice",
        assistant_commitment="Saved as a pending task.",
        lane="work",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        task_text="send the invoice",
        lane="work",
    )

    pending_tasks = task_service.get_tasks(
        user_id="U123",
        lane="work",
        status="pending",
        limit=10,
    )
    done_tasks = task_service.get_tasks(
        user_id="U123",
        lane="work",
        status="done",
        limit=10,
    )

    assert created["created"] is True
    assert result["status"] == "updated"
    assert result["updated"] is True
    assert result["deleted"] is False
    assert result["task"]["id"] == created["id"]
    assert result["task"]["status"] == "done"
    assert pending_tasks == []
    assert len(done_tasks) == 1
    assert done_tasks[0]["id"] == created["id"]


def test_mark_task_done_returns_not_found_when_no_match(isolated_task_db: Path):
    result = task_service.mark_task_done(
        user_id="U123",
        task_text="send the invoice",
        lane="work",
    )

    assert result["status"] == "not_found"
    assert result["updated"] is False
    assert result["deleted"] is False
    assert result["task"] is None


def test_remove_task_deletes_matching_pending_task(isolated_task_db: Path):
    created = task_service.add_task(
        user_id="U123",
        source_message="add task book the photographer",
        task_text="Book the photographer",
        assistant_commitment="Saved as a pending task.",
        lane="work",
    )

    result = task_service.remove_task(
        user_id="U123",
        task_text="book the photographer",
        lane="work",
        status="pending",
    )

    remaining_tasks = task_service.get_tasks(
        user_id="U123",
        lane="work",
        status="pending",
        limit=10,
    )

    assert created["created"] is True
    assert result["status"] == "deleted"
    assert result["deleted"] is True
    assert result["updated"] is False
    assert result["task"]["id"] == created["id"]
    assert remaining_tasks == []


def test_remove_task_returns_not_found_when_no_match(isolated_task_db: Path):
    result = task_service.remove_task(
        user_id="U123",
        task_text="book the photographer",
        lane="work",
        status="pending",
    )

    assert result["status"] == "not_found"
    assert result["deleted"] is False
    assert result["updated"] is False
    assert result["task"] is None
