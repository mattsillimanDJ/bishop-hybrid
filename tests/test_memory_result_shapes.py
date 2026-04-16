import pytest

from app.routes import slack as slack_route


def test_get_safe_memory_items_handles_none():
    results = slack_route.get_safe_memory_items(None, "work")
    assert results == []


def test_get_safe_memory_items_handles_non_list():
    results = slack_route.get_safe_memory_items("bad-data", "work")
    assert results == []


def test_get_safe_memory_items_filters_invalid_items():
    raw = [
        None,
        "bad",
        {"content": "valid memory", "lane": "work"},
        {"lane": "work"},  # missing content
    ]

    results = slack_route.get_safe_memory_items(raw, "work")

    assert len(results) == 1
    assert results[0]["content"] == "valid memory"


def test_format_memory_line_handles_missing_fields():
    item = {
        "content": "test memory"
        # missing lane, visibility, owner
    }

    line = slack_route.format_memory_line(item)

    assert "test memory" in line


def test_was_memory_deleted_handles_bad_shape():
    assert slack_route.was_memory_deleted(None) is False
    assert slack_route.was_memory_deleted("bad") is False
    assert slack_route.was_memory_deleted({}) is False


def test_get_deleted_memory_lane_fallback():
    result = {"deleted": True}
    lane = slack_route.get_deleted_memory_lane(result, "fallback-lane")

    assert lane == "fallback-lane"
