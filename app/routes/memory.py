from fastapi import APIRouter
from app.services.memory_service import get_memories, add_memory

router = APIRouter()


@router.get("/memory")
def list_memory(user_id: str = "matt", limit: int = 20):
    return {"memories": get_memories(user_id=user_id, limit=limit)}


@router.post("/memory/add")
def create_memory(user_id: str = "matt", category: str = "note", content: str = ""):
    if not content.strip():
        return {"ok": False, "error": "content is required"}

    memory = add_memory(user_id=user_id, category=category, content=content)
    return {"ok": True, "memory": memory}
