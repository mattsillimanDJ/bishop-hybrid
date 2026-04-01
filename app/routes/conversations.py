from fastapi import APIRouter, Query
from app.services.conversation_log_service import get_recent_conversations

router = APIRouter()


@router.get("/conversations")
def read_recent_conversations(limit: int = Query(default=20, le=100)):
    return {
        "count": limit,
        "items": get_recent_conversations(limit=limit),
    }

