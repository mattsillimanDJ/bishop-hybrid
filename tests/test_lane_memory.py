import pytest

from app.services import memory_service
from app.services.memory_service import (
    add_memory,
    get_memories,
    search_memories,
    delete_memory_by_query,
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


def test_shared_memory_is_visible():
    user_id = "test_user_shared"

    add_memory(user_id, "note", "family shared item", lane="family", visibility="shared")

    matt_memories = get_memories(user_id=user_id, lane="matt")
    carmen_memories = get_memories(user_id=user_id, lane="carmen")

    assert any("family shared item" in m["content"] for m in matt_memories)
    assert any("family shared item" in m["content"] for m in carmen_memories)


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


def test_search_returns_shared_and_lane_specific():
    user_id = "test_user_shared_search"

    add_memory(user_id, "note", "shared idea", lane="family", visibility="shared")
    add_memory(user_id, "note", "work only idea", lane="work", visibility="private")

    results = search_memories(user_id=user_id, query="idea", lane="work")

    assert any("shared idea" in r["content"] for r in results)
    assert any("work only idea" in r["content"] for r in results)


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
