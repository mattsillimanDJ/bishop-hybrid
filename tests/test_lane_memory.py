import pytest

from app.services import memory_service
from app.services.memory_service import (
    add_memory,
    cleanup_duplicate_memories,
    delete_memory_by_query,
    get_memories,
    search_memories,
)


@pytest.fixture(autouse=True)
def use_temp_memory_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(memory_service, "DB_PATH", test_db_path)


def test_private_memory_is_isolated():
    user_id = "test_user"

    add_memory(user_id, "note", "matt private note", lane="matt", visibility="private")
    add_memory(user_id, "note", "carmen private note", lane="carmen", visibility="private")

    matt_memories = get_memories(user_id=user_id, lane="matt")
    carmen_memories = get_memories(user_id=user_id, lane="carmen")

    assert any("matt private note" in m["content"] for m in matt_memories)
    assert not any("carmen private note" in m["content"] for m in matt_memories)

    assert any("carmen private note" in m["content"] for m in carmen_memories)
    assert not any("matt private note" in m["content"] for m in carmen_memories)


def test_shared_memory_is_visible_in_same_lane():
    matt_user_id = "matt_user_shared_same_lane"
    carmen_user_id = "carmen_user_shared_same_lane"

    add_memory(matt_user_id, "note", "family shared item", lane="family", visibility="shared")

    matt_memories = get_memories(user_id=matt_user_id, lane="family")
    carmen_memories = get_memories(user_id=carmen_user_id, lane="family")

    assert any("family shared item" in m["content"] for m in matt_memories)
    assert any("family shared item" in m["content"] for m in carmen_memories)


def test_shared_memory_is_not_visible_in_other_lanes():
    user_id = "test_user_shared_other_lane"

    add_memory(user_id, "note", "family shared item", lane="family", visibility="shared")

    work_memories = get_memories(user_id=user_id, lane="work")
    dj_memories = get_memories(user_id=user_id, lane="dj")

    assert not any("family shared item" in m["content"] for m in work_memories)
    assert not any("family shared item" in m["content"] for m in dj_memories)


def test_search_respects_lane():
    user_id = "test_user_search"

    add_memory(user_id, "note", "dj set idea", lane="dj", visibility="private")
    add_memory(user_id, "note", "work campaign idea", lane="work", visibility="private")

    dj_results = search_memories(user_id=user_id, query="idea", lane="dj")

    assert any("dj set idea" in r["content"] for r in dj_results)
    assert not any("work campaign idea" in r["content"] for r in dj_results)


def test_delete_respects_lane():
    user_id = "test_user_delete"

    add_memory(user_id, "note", "delete me matt", lane="matt", visibility="private")
    add_memory(user_id, "note", "delete me carmen", lane="carmen", visibility="private")

    result = delete_memory_by_query(user_id=user_id, query="delete me", lane="matt")

    assert result["deleted"] is True
    assert result["lane"] == "matt"

    remaining = get_memories(user_id=user_id, lane="carmen")
    assert any("delete me carmen" in m["content"] for m in remaining)


def test_same_memory_text_can_exist_in_multiple_lanes():
    user_id = "test_user_multi"

    add_memory(user_id, "note", "same memory", lane="work", visibility="private")
    add_memory(user_id, "note", "same memory", lane="dj", visibility="private")

    work_memories = get_memories(user_id=user_id, lane="work")
    dj_memories = get_memories(user_id=user_id, lane="dj")

    assert any("same memory" in m["content"] for m in work_memories)
    assert any("same memory" in m["content"] for m in dj_memories)


def test_delete_only_affects_one_lane_with_same_text():
    user_id = "test_user_delete_lane"

    add_memory(user_id, "note", "same delete target", lane="work", visibility="private")
    add_memory(user_id, "note", "same delete target", lane="dj", visibility="private")

    result = delete_memory_by_query(user_id=user_id, query="same delete target", lane="work")

    assert result["deleted"] is True
    assert result["lane"] == "work"

    work_memories = get_memories(user_id=user_id, lane="work")
    dj_memories = get_memories(user_id=user_id, lane="dj")

    assert not any("same delete target" in m["content"] for m in work_memories)
    assert any("same delete target" in m["content"] for m in dj_memories)


def test_search_returns_shared_and_lane_specific_in_same_lane():
    matt_user_id = "matt_user_shared_search_same_lane"
    carmen_user_id = "carmen_user_shared_search_same_lane"

    add_memory(matt_user_id, "note", "shared idea", lane="family", visibility="shared")
    add_memory(carmen_user_id, "note", "family only idea", lane="family", visibility="private")

    matt_results = search_memories(user_id=matt_user_id, query="idea", lane="family")
    carmen_results = search_memories(user_id=carmen_user_id, query="idea", lane="family")

    assert any("shared idea" in r["content"] for r in matt_results)
    assert any("family only idea" in r["content"] for r in carmen_results)
    assert any("shared idea" in r["content"] for r in carmen_results)
    assert not any("family only idea" in r["content"] for r in matt_results)


def test_get_memories_is_clean_per_lane_even_with_duplicates():
    user_id = "test_user_clean"

    add_memory(user_id, "note", "duplicate memory", lane="work", visibility="private")
    add_memory(user_id, "note", "duplicate memory", lane="dj", visibility="private")

    work_memories = get_memories(user_id=user_id, lane="work")
    dj_memories = get_memories(user_id=user_id, lane="dj")

    assert len(work_memories) == 1
    assert len(dj_memories) == 1

    assert work_memories[0]["content"] == "duplicate memory"
    assert dj_memories[0]["content"] == "duplicate memory"


def test_private_memory_is_isolated_between_users_in_same_lane():
    matt_user_id = "matt_user"
    carmen_user_id = "carmen_user"

    add_memory(matt_user_id, "note", "matt private family note", lane="family", visibility="private")
    add_memory(carmen_user_id, "note", "carmen private family note", lane="family", visibility="private")

    matt_memories = get_memories(user_id=matt_user_id, lane="family")
    carmen_memories = get_memories(user_id=carmen_user_id, lane="family")

    assert any("matt private family note" in m["content"] for m in matt_memories)
    assert not any("carmen private family note" in m["content"] for m in matt_memories)

    assert any("carmen private family note" in m["content"] for m in carmen_memories)
    assert not any("matt private family note" in m["content"] for m in carmen_memories)


def test_search_private_memory_is_isolated_between_users_in_same_lane():
    matt_user_id = "matt_user_search"
    carmen_user_id = "carmen_user_search"

    add_memory(matt_user_id, "note", "shared phrase matt private", lane="family", visibility="private")
    add_memory(carmen_user_id, "note", "shared phrase carmen private", lane="family", visibility="private")

    matt_results = search_memories(user_id=matt_user_id, query="shared phrase", lane="family")
    carmen_results = search_memories(user_id=carmen_user_id, query="shared phrase", lane="family")

    assert any("shared phrase matt private" in r["content"] for r in matt_results)
    assert not any("shared phrase carmen private" in r["content"] for r in matt_results)

    assert any("shared phrase carmen private" in r["content"] for r in carmen_results)
    assert not any("shared phrase matt private" in r["content"] for r in carmen_results)


def test_delete_private_memory_only_affects_requesting_user_in_same_lane():
    matt_user_id = "matt_user_delete"
    carmen_user_id = "carmen_user_delete"

    add_memory(matt_user_id, "note", "same family delete target", lane="family", visibility="private")
    add_memory(carmen_user_id, "note", "same family delete target", lane="family", visibility="private")

    result = delete_memory_by_query(
        user_id=matt_user_id,
        query="same family delete target",
        lane="family",
    )

    assert result["deleted"] is True
    assert result["lane"] == "family"

    matt_memories = get_memories(user_id=matt_user_id, lane="family")
    carmen_memories = get_memories(user_id=carmen_user_id, lane="family")

    assert not any("same family delete target" in m["content"] for m in matt_memories)
    assert any("same family delete target" in m["content"] for m in carmen_memories)


def test_shared_memory_is_visible_across_different_users_in_same_lane():
    matt_user_id = "matt_user_shared"
    carmen_user_id = "carmen_user_shared"

    add_memory(matt_user_id, "note", "matt shared family item", lane="family", visibility="shared")

    matt_memories = get_memories(user_id=matt_user_id, lane="family")
    carmen_memories = get_memories(user_id=carmen_user_id, lane="family")

    assert any("matt shared family item" in m["content"] for m in matt_memories)
    assert any("matt shared family item" in m["content"] for m in carmen_memories)


def test_shared_search_is_visible_across_different_users_in_same_lane():
    matt_user_id = "matt_user_shared_search"
    carmen_user_id = "carmen_user_shared_search"

    add_memory(matt_user_id, "note", "lane shared idea", lane="family", visibility="shared")

    matt_results = search_memories(user_id=matt_user_id, query="shared idea", lane="family")
    carmen_results = search_memories(user_id=carmen_user_id, query="shared idea", lane="family")

    assert any("lane shared idea" in r["content"] for r in matt_results)
    assert any("lane shared idea" in r["content"] for r in carmen_results)


def test_shared_memory_is_not_visible_across_different_users_in_other_lanes():
    matt_user_id = "matt_user_shared_other_lane"
    carmen_user_id = "carmen_user_shared_other_lane"

    add_memory(matt_user_id, "note", "family shared item", lane="family", visibility="shared")

    carmen_work_memories = get_memories(user_id=carmen_user_id, lane="work")
    carmen_dj_memories = get_memories(user_id=carmen_user_id, lane="dj")

    assert not any("family shared item" in m["content"] for m in carmen_work_memories)
    assert not any("family shared item" in m["content"] for m in carmen_dj_memories)


def test_memory_records_include_owner_user_id():
    user_id = "owner_field_user"

    created = add_memory(
        user_id=user_id,
        category="note",
        content="owner field memory",
        lane="work",
        visibility="private",
    )

    memories = get_memories(user_id=user_id, lane="work")

    assert created["owner_user_id"] == user_id
    assert len(memories) == 1
    assert memories[0]["owner_user_id"] == user_id
    assert memories[0]["content"] == "owner field memory"


def test_exact_duplicate_in_same_scope_is_not_stored_twice():
    user_id = "dedupe_exact"

    add_memory(user_id, "note", "remember the milk", lane="work", visibility="private")
    add_memory(user_id, "note", "remember the milk", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    matches = [m for m in memories if m["content"] == "remember the milk"]
    assert len(matches) == 1


def test_exact_duplicate_is_case_and_whitespace_insensitive():
    user_id = "dedupe_case_ws"

    add_memory(user_id, "note", "Remember The Milk", lane="work", visibility="private")
    add_memory(user_id, "note", "  remember the milk  ", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    assert len(memories) == 1
    assert memories[0]["content"] == "Remember The Milk"


def test_new_shorter_prefix_is_not_stored_when_longer_exists():
    user_id = "dedupe_prefix_skip"

    add_memory(user_id, "note", "buy groceries for the week", lane="work", visibility="private")
    add_memory(user_id, "note", "buy groceries", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    contents = [m["content"] for m in memories]
    assert "buy groceries for the week" in contents
    assert "buy groceries" not in contents
    assert len(memories) == 1


def test_new_shorter_suffix_is_not_stored_when_longer_exists():
    user_id = "dedupe_suffix_skip"

    add_memory(user_id, "note", "please buy groceries", lane="work", visibility="private")
    add_memory(user_id, "note", "buy groceries", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    contents = [m["content"] for m in memories]
    assert "please buy groceries" in contents
    assert "buy groceries" not in contents
    assert len(memories) == 1


def test_new_longer_supersedes_existing_shorter_prefix():
    user_id = "dedupe_prefix_supersede"

    add_memory(user_id, "note", "buy groceries", lane="work", visibility="private")
    add_memory(user_id, "note", "buy groceries for the week", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    contents = [m["content"] for m in memories]
    assert contents == ["buy groceries for the week"]


def test_new_longer_supersedes_existing_shorter_suffix():
    user_id = "dedupe_suffix_supersede"

    add_memory(user_id, "note", "buy groceries", lane="work", visibility="private")
    add_memory(user_id, "note", "please buy groceries", lane="work", visibility="private")

    memories = get_memories(user_id=user_id, lane="work")
    contents = [m["content"] for m in memories]
    assert contents == ["please buy groceries"]


def test_dedupe_does_not_cross_lanes():
    user_id = "dedupe_cross_lane"

    add_memory(user_id, "note", "shared phrase", lane="work", visibility="private")
    add_memory(user_id, "note", "shared phrase", lane="dj", visibility="private")

    work_memories = get_memories(user_id=user_id, lane="work")
    dj_memories = get_memories(user_id=user_id, lane="dj")

    assert any(m["content"] == "shared phrase" for m in work_memories)
    assert any(m["content"] == "shared phrase" for m in dj_memories)


def test_dedupe_does_not_cross_visibility():
    user_id = "dedupe_cross_visibility"

    add_memory(user_id, "note", "same text different visibility", lane="family", visibility="private")
    add_memory(user_id, "note", "same text different visibility", lane="family", visibility="shared")

    memories = get_memories(user_id=user_id, lane="family")
    matches = [m for m in memories if m["content"] == "same text different visibility"]
    assert len(matches) == 2
    visibilities = {m["visibility"] for m in matches}
    assert visibilities == {"private", "shared"}


def test_dedupe_does_not_cross_owners():
    matt_user_id = "dedupe_owner_matt"
    carmen_user_id = "dedupe_owner_carmen"

    add_memory(matt_user_id, "note", "same owner-scoped text", lane="family", visibility="private")
    add_memory(carmen_user_id, "note", "same owner-scoped text", lane="family", visibility="private")

    matt_memories = get_memories(user_id=matt_user_id, lane="family")
    carmen_memories = get_memories(user_id=carmen_user_id, lane="family")

    assert any(m["content"] == "same owner-scoped text" for m in matt_memories)
    assert any(m["content"] == "same owner-scoped text" for m in carmen_memories)


def _raw_insert(conn, user_id, content, lane, visibility):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_entries
        (user_id, owner_user_id, category, content, lane, visibility)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, user_id, "note", content, lane, visibility),
    )
    conn.commit()
    return cur.lastrowid


def test_cleanup_removes_exact_and_truncated_duplicates_in_scope():
    from app.services.memory_service import init_db, get_connection

    init_db()
    conn = get_connection()
    user_id = "cleanup_user"

    longer_id = _raw_insert(
        conn, user_id, "Matt values exact terminal instructions and full-file replacements for coding work",
        "matt", "private",
    )
    shorter_id = _raw_insert(
        conn, user_id, "Matt values exact terminal instructions and full-file",
        "matt", "private",
    )
    exact_first_id = _raw_insert(
        conn, user_id, "repeat me", "matt", "private",
    )
    exact_second_id = _raw_insert(
        conn, user_id, "repeat me", "matt", "private",
    )
    other_lane_id = _raw_insert(
        conn, user_id, "Matt values exact terminal instructions and full-file",
        "work", "private",
    )
    conn.close()

    result = cleanup_duplicate_memories()

    assert result["dry_run"] is False
    assert shorter_id in result["deleted_ids"]
    assert exact_second_id in result["deleted_ids"]
    assert longer_id not in result["deleted_ids"]
    assert exact_first_id not in result["deleted_ids"]
    assert other_lane_id not in result["deleted_ids"]

    remaining = get_memories(user_id=user_id, lane="matt")
    contents = [m["content"] for m in remaining]
    assert "Matt values exact terminal instructions and full-file replacements for coding work" in contents
    assert "repeat me" in contents
    assert "Matt values exact terminal instructions and full-file" not in contents
    assert len([c for c in contents if c == "repeat me"]) == 1

    work_memories = get_memories(user_id=user_id, lane="work")
    assert any(
        m["content"] == "Matt values exact terminal instructions and full-file"
        for m in work_memories
    )


def test_cleanup_dry_run_does_not_delete():
    from app.services.memory_service import init_db, get_connection

    init_db()
    conn = get_connection()
    user_id = "cleanup_dry_run_user"
    longer_id = _raw_insert(conn, user_id, "the full sentence here", "matt", "private")
    shorter_id = _raw_insert(conn, user_id, "the full sentence", "matt", "private")
    conn.close()

    result = cleanup_duplicate_memories(dry_run=True)

    assert result["dry_run"] is True
    assert shorter_id in result["deleted_ids"]
    assert longer_id not in result["deleted_ids"]

    remaining = get_memories(user_id=user_id, lane="matt")
    contents = [m["content"] for m in remaining]
    assert "the full sentence here" in contents
    assert "the full sentence" in contents


def test_cleanup_respects_scope_boundaries():
    from app.services.memory_service import init_db, get_connection

    init_db()
    conn = get_connection()
    _raw_insert(conn, "user_a", "same content", "family", "private")
    _raw_insert(conn, "user_b", "same content", "family", "private")
    _raw_insert(conn, "user_a", "same content", "family", "shared")
    _raw_insert(conn, "user_a", "same content", "work", "private")
    conn.close()

    result = cleanup_duplicate_memories()

    assert result["deleted"] == 0
