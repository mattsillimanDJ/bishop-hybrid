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


def test_dedupe_collapses_exact_duplicates_keeps_first():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "dinner at 7",
        },
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "dinner at 7",
        },
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "book the vet",
        },
    ]

    deduped = slack_route.dedupe_memory_items(items)

    assert [i["content"] for i in deduped] == ["dinner at 7", "book the vet"]


def test_dedupe_is_case_and_whitespace_insensitive():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "Dinner at 7",
        },
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "  dinner at 7  ",
        },
    ]

    deduped = slack_route.dedupe_memory_items(items)

    assert len(deduped) == 1
    assert deduped[0]["content"] == "Dinner at 7"


def test_dedupe_preserves_items_differing_by_lane_visibility_or_owner():
    items = [
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "same note",
        },
        {
            "lane": "work",
            "visibility": "shared",
            "owner_user_id": "matt",
            "content": "same note",
        },
        {
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
            "content": "same note",
        },
        {
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "carmen",
            "content": "same note",
        },
    ]

    deduped = slack_route.dedupe_memory_items(items)

    assert len(deduped) == 4


def test_rerank_pushes_profile_and_preference_to_bottom_stably():
    items = [
        {"category": "profile", "content": "user's name is matt"},
        {"category": "note", "content": "dinner at 7"},
        {"category": "preference", "content": "prefers clear help"},
        {"category": "note", "content": "book the vet"},
        {"category": "", "content": "untagged actionable item"},
    ]

    reranked = slack_route.rerank_memory_items(items)

    assert [i["content"] for i in reranked] == [
        "dinner at 7",
        "book the vet",
        "untagged actionable item",
        "user's name is matt",
        "prefers clear help",
    ]


def test_rerank_is_case_insensitive_on_category():
    items = [
        {"category": "Profile", "content": "identity line"},
        {"category": "note", "content": "actionable"},
    ]

    reranked = slack_route.rerank_memory_items(items)

    assert [i["content"] for i in reranked] == ["actionable", "identity line"]


def test_suppress_boilerplate_filters_known_identity_lines():
    items = [
        {"content": "User's name is Matt."},
        {"content": "Matt is an advertising executive and DJ."},
        {"content": "Bishop is a private AI workspace for work, DJ/music, family, Carmen, and general life."},
        {"content": "Matt prefers clear, practical, strategic help."},
        {"content": "Matt wants Bishop to feel like a personal AI operating system, not a generic chatbot."},
        {"content": "dinner at 7"},
    ]

    filtered = slack_route.suppress_boilerplate_memory_items(items)

    assert [i["content"] for i in filtered] == ["dinner at 7"]


def test_suppress_boilerplate_is_case_and_whitespace_insensitive():
    items = [
        {"content": "  user's name is matt.  "},
        {"content": "USER'S NAME IS MATT."},
        {"content": "Matt's favorite color is blue."},
    ]

    filtered = slack_route.suppress_boilerplate_memory_items(items)

    assert [i["content"] for i in filtered] == ["Matt's favorite color is blue."]


def test_suppress_boilerplate_preserves_non_boilerplate_profile_notes():
    items = [
        {"content": "User's name is Matt.", "category": "profile"},
        {"content": "Matt's blood type is O+.", "category": "profile"},
        {"content": "Matt prefers vegan meals.", "category": "preference"},
    ]

    filtered = slack_route.suppress_boilerplate_memory_items(items)
    contents = [i["content"] for i in filtered]

    assert "User's name is Matt." not in contents
    assert "Matt's blood type is O+." in contents
    assert "Matt prefers vegan meals." in contents


def test_build_lane_memory_response_suppresses_boilerplate_by_default(monkeypatch):
    raw = [
        {
            "content": "dinner at 7",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "note",
        },
        {
            "content": "User's name is Matt.",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "profile",
        },
    ]

    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=20: raw,
    )
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = slack_route.build_lane_memory_response(user_id="matt", lane="family")

    assert "dinner at 7" in response
    assert "User's name is Matt." not in response


def test_build_lane_memory_response_include_boilerplate_shows_all(monkeypatch):
    raw = [
        {
            "content": "dinner at 7",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "note",
        },
        {
            "content": "User's name is Matt.",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "profile",
        },
    ]

    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=20: raw,
    )
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = slack_route.build_lane_memory_response(
        user_id="matt", lane="family", include_boilerplate=True
    )

    assert "dinner at 7" in response
    assert "User's name is Matt." in response


def test_build_lane_memory_response_falls_back_to_boilerplate_when_only_boilerplate_exists(
    monkeypatch,
):
    raw = [
        {
            "content": "User's name is Matt.",
            "lane": "matt",
            "visibility": "private",
            "owner_user_id": "matt",
            "category": "profile",
        },
        {
            "content": "Matt prefers clear, practical, strategic help.",
            "lane": "matt",
            "visibility": "private",
            "owner_user_id": "matt",
            "category": "preference",
        },
    ]

    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=20: raw,
    )
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = slack_route.build_lane_memory_response(user_id="matt", lane="matt")

    assert "I do not have any saved memory yet" not in response
    assert "Here is what I remember in the matt lane:" in response
    assert "User's name is Matt." in response
    assert "Matt prefers clear, practical, strategic help." in response


def test_build_lane_memory_response_empty_lane_still_returns_empty_state(monkeypatch):
    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=20: [],
    )
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = slack_route.build_lane_memory_response(user_id="matt", lane="matt")

    assert response == "I do not have any saved memory yet in the matt lane."


def test_build_lane_memory_response_dedupes_and_reranks(monkeypatch):
    raw = [
        {
            "content": "dinner at 7",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "note",
        },
        {
            "content": "User's name is Matt.",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "profile",
        },
        {
            "content": "dinner at 7",
            "lane": "family",
            "visibility": "shared",
            "owner_user_id": "matt",
            "category": "note",
        },
        {
            "content": "book the vet",
            "lane": "family",
            "visibility": "private",
            "owner_user_id": "matt",
            "category": "note",
        },
    ]

    monkeypatch.setattr(
        slack_route,
        "get_memories",
        lambda user_id, lane, limit=20: raw,
    )
    monkeypatch.setattr(
        slack_route,
        "get_display_name_for_bishop_user_id",
        lambda user_id: "Matt",
    )

    response = slack_route.build_lane_memory_response(user_id="matt", lane="family")

    lines = response.splitlines()
    assert lines[0] == "Here is what I remember in the family lane:"
    body = lines[1:]

    assert len(body) == 2
    assert "dinner at 7" in body[0]
    assert "book the vet" in body[1]
    assert "User's name is Matt." not in response

    full_response = slack_route.build_lane_memory_response(
        user_id="matt", lane="family", include_boilerplate=True
    )
    full_body = full_response.splitlines()[1:]
    assert len(full_body) == 3
    assert "dinner at 7" in full_body[0]
    assert "book the vet" in full_body[1]
    assert "User's name is Matt." in full_body[2]
