from app.services.memory_service import (
    add_memory,
    get_memories,
    search_memories,
    delete_memory_by_query,
)


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

