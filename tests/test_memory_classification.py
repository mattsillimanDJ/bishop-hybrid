import pytest

from app.services import memory_service
from app.services.memory_service import add_memory, infer_memory_category


@pytest.fixture(autouse=True)
def use_temp_memory_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(memory_service, "DB_PATH", test_db_path)


def test_infer_workflow_preference_becomes_preference():
    assert infer_memory_category("Matt prefers concise replies.", "note") == "preference"
    assert (
        infer_memory_category("Always use markdown tables for lists", "note")
        == "preference"
    )
    assert (
        infer_memory_category(
            "Matt wants bishop to confirm before sending email.", ""
        )
        == "preference"
    )
    assert (
        infer_memory_category("Never mock the database in tests.", "note")
        == "preference"
    )


def test_infer_durable_identity_becomes_profile():
    assert (
        infer_memory_category("Matt is an advertising executive and DJ.", "note")
        == "profile"
    )
    assert infer_memory_category("Matt lives in Brooklyn.", "note") == "profile"
    assert infer_memory_category("Carmen is Matt's wife.", "note") == "profile"
    assert infer_memory_category("User's name is Matt.", "") == "profile"


def test_infer_ambiguous_memory_stays_note():
    assert infer_memory_category("dinner at 7", "note") == "note"
    assert infer_memory_category("book the vet tomorrow", "") == "note"
    assert infer_memory_category("the meeting moved to 3pm", "note") == "note"
    assert infer_memory_category("", "note") == "note"


def test_infer_preserves_explicit_non_generic_category():
    assert (
        infer_memory_category("Matt is an advertising executive", "preference")
        == "preference"
    )
    assert (
        infer_memory_category("Matt prefers concise replies", "profile") == "profile"
    )
    assert infer_memory_category("dinner at 7", "task") == "task"
    assert infer_memory_category("Matt lives in Brooklyn", "reference") == "reference"


def test_add_memory_upgrades_generic_note_to_preference():
    row = add_memory(
        user_id="matt",
        category="note",
        content="Matt prefers concise, practical replies.",
        lane="matt",
        visibility="private",
    )

    assert row["category"] == "preference"
    assert row["content"] == "Matt prefers concise, practical replies."


def test_add_memory_upgrades_blank_category_to_profile():
    row = add_memory(
        user_id="matt",
        category="",
        content="Matt lives in Brooklyn.",
        lane="matt",
        visibility="private",
    )

    assert row["category"] == "profile"


def test_add_memory_keeps_ambiguous_note():
    row = add_memory(
        user_id="matt",
        category="note",
        content="dinner at 7",
        lane="matt",
        visibility="private",
    )

    assert row["category"] == "note"


def test_add_memory_preserves_explicit_non_generic_category():
    row = add_memory(
        user_id="matt",
        category="preference",
        content="Matt is an advertising executive",
        lane="matt",
        visibility="private",
    )

    assert row["category"] == "preference"


def test_add_memory_classification_does_not_break_dedupe():
    first = add_memory(
        user_id="matt",
        category="note",
        content="Matt prefers concise replies",
        lane="matt",
        visibility="private",
    )
    second = add_memory(
        user_id="matt",
        category="note",
        content="Matt prefers concise replies",
        lane="matt",
        visibility="private",
    )

    assert first["category"] == "preference"
    assert second["id"] == first["id"]
    assert second["category"] == "preference"
