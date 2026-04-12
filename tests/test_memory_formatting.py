from app.routes import slack as slack_route


def test_format_memory_line_with_owner():
    item = {
        "lane": "family",
        "visibility": "shared",
        "content": "dinner at 7",
        "owner_display_name": "Matt",
    }

    line = slack_route.format_memory_line(item)

    assert line == "* Matt shared in family: dinner at 7"


def test_format_memory_line_without_owner():
    item = {
        "lane": "family",
        "visibility": "shared",
        "content": "dinner at 7",
        "owner_display_name": "",
    }

    line = slack_route.format_memory_line(item)

    assert line == "* shared in family: dinner at 7"


def test_format_memory_lines_multiple():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "content": "dinner at 7",
            "owner_display_name": "Matt",
        },
        {
            "lane": "family",
            "visibility": "private",
            "content": "buy gift",
            "owner_display_name": "Carmen",
        },
    ]

    lines = slack_route.format_memory_lines(items)

    assert lines == [
        "* Matt shared in family: dinner at 7",
        "* Carmen private in family: buy gift",
    ]


def test_normalize_memory_item_fills_missing_fields(monkeypatch):
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    raw = {
        "content": "test memory",
    }

    normalized = slack_route.normalize_memory_item(raw, fallback_lane="family")

    assert normalized["content"] == "test memory"
    assert normalized["lane"] == "family"
    assert normalized["visibility"] == "unknown"
    assert normalized["owner_user_id"] == "unknown"
    assert normalized["owner_display_name"] == "Matt"


def test_get_safe_memory_items_filters_invalid(monkeypatch):
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    raw_items = [
        {"content": "valid memory"},
        {"content": ""},
        {"no_content": True},
        "bad type",
    ]

    results = slack_route.get_safe_memory_items(raw_items, fallback_lane="family")

    assert len(results) == 1
    assert results[0]["content"] == "valid memory"


def test_format_memory_lines_empty():
    lines = slack_route.format_memory_lines([])

    assert lines == []
