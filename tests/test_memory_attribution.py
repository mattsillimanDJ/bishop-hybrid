from app.routes import slack as slack_route


def test_normalize_memory_item_adds_known_owner_display_name():
    item = {
        "content": "dinner at 7",
        "lane": "family",
        "visibility": "shared",
        "owner_user_id": "matt",
    }

    normalized = slack_route.normalize_memory_item(item, fallback_lane="family")

    assert normalized is not None
    assert normalized["owner_user_id"] == "matt"
    assert normalized["owner_display_name"] == "Matt"
    assert normalized["content"] == "dinner at 7"
    assert normalized["lane"] == "family"
    assert normalized["visibility"] == "shared"


def test_normalize_memory_item_falls_back_to_user_id_when_owner_missing():
    item = {
        "content": "book the vet",
        "lane": "family",
        "visibility": "private",
        "user_id": "carmen",
    }

    normalized = slack_route.normalize_memory_item(item, fallback_lane="family")

    assert normalized is not None
    assert normalized["owner_user_id"] == "carmen"
    assert normalized["owner_display_name"] == "Carmen"
    assert normalized["content"] == "book the vet"


def test_normalize_memory_item_falls_back_to_unknown_user_id_display():
    item = {
        "content": "mystery note",
        "lane": "work",
        "visibility": "private",
        "owner_user_id": "unknown_user",
    }

    normalized = slack_route.normalize_memory_item(item, fallback_lane="work")

    assert normalized is not None
    assert normalized["owner_user_id"] == "unknown_user"
    assert normalized["owner_display_name"] == "unknown_user"
    assert normalized["content"] == "mystery note"


def test_format_memory_lines_includes_owner_display_name():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "content": "dinner at 7",
            "owner_user_id": "matt",
            "owner_display_name": "Matt",
        }
    ]

    lines = slack_route.format_memory_lines(items)

    assert lines == ["* Matt shared in family: dinner at 7"]


def test_format_memory_lines_handles_multiple_people():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "content": "dinner at 7",
            "owner_user_id": "matt",
            "owner_display_name": "Matt",
        },
        {
            "lane": "family",
            "visibility": "private",
            "content": "book the vet",
            "owner_user_id": "carmen",
            "owner_display_name": "Carmen",
        },
    ]

    lines = slack_route.format_memory_lines(items)

    assert "* Matt shared in family: dinner at 7" in lines
    assert "* Carmen private in family: book the vet" in lines


def test_format_memory_lines_falls_back_when_display_name_empty():
    items = [
        {
            "lane": "work",
            "visibility": "private",
            "content": "mystery note",
            "owner_user_id": "unknown_user",
            "owner_display_name": "",
        }
    ]

    lines = slack_route.format_memory_lines(items)

    assert lines == ["* private in work: mystery note"]


def test_get_safe_memory_items_adds_attribution_for_valid_items():
    raw_items = [
        {
            "content": "dinner at 7",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
        {
            "content": "book the vet",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "carmen",
        },
    ]

    items = slack_route.get_safe_memory_items(raw_items, fallback_lane="family")

    assert len(items) == 2
    assert items[0]["owner_display_name"] == "Matt"
    assert items[1]["owner_display_name"] == "Carmen"


def test_get_safe_memory_items_ignores_invalid_entries():
    raw_items = [
        {"content": "", "lane": "family", "visibility": "shared", "owner_user_id": "matt"},
        {"visibility": "private"},
        "bad-item",
        {
            "content": "valid note",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
        },
    ]

    items = slack_route.get_safe_memory_items(raw_items, fallback_lane="family")

    assert len(items) == 1
    assert items[0]["content"] == "valid note"
    assert items[0]["owner_display_name"] == "Matt"
