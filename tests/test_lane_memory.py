import pytest

from app.services import memory_service
from app.services.memory_service import (
    add_memory,
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
