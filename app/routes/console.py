import sqlite3
from typing import Any

from fastapi import APIRouter, Query

from app.config import settings
from app.services.conversation_log_service import get_recent_conversations
from app.services.focus_service import VALID_FOCUSES, get_active_focus
from app.services.memory_service import get_connection as get_memory_connection
from app.services.memory_service import get_memories
from app.services.mode_service import get_mode
from app.services.provider_state_service import get_provider_resolution
from app.services.research_service import validate_research_config
from app.services.task_service import get_connection as get_task_connection


router = APIRouter(prefix="/console", tags=["console"])

CONSOLE_PHASE = "phase_1_read_only"
CONSOLE_USER_ID = "matt"
CONSOLE_DEFAULT_LANE = "matt"

# TODO: Phase 1 is internal/private but does not add a new auth system.
# Add console authentication before exposing these endpoints outside Bishop's
# trusted private runtime.

PROJECTS = [
    {
        "id": "bishop",
        "name": "Bishop",
        "description": "Bishop system, control plane, and agent improvements.",
        "focus_key": "bishop",
        "recommended_modes": ["product", "work"],
    },
    {
        "id": "stemlab",
        "name": "StemLab",
        "description": "AI music product work for DJ and producer stem workflows.",
        "focus_key": "stemlab",
        "recommended_modes": ["stemlab", "product"],
    },
    {
        "id": "work",
        "name": "Work",
        "description": "Matt's work lane and professional operating context.",
        "focus_key": "work",
        "recommended_modes": ["work", "cmo"],
    },
    {
        "id": "dj",
        "name": "DJ",
        "description": "DJ, music, and creative performance context.",
        "focus_key": "dj",
        "recommended_modes": ["creative", "default"],
    },
    {
        "id": "events",
        "name": "Events",
        "description": "Event production, logistics, and planning context.",
        "focus_key": "events",
        "recommended_modes": ["events", "work"],
    },
    {
        "id": "website",
        "name": "Website",
        "description": "Website, portfolio, and public web presence work.",
        "focus_key": "website",
        "recommended_modes": ["website", "product"],
    },
    {
        "id": "personal",
        "name": "Personal",
        "description": "Personal planning and private life context.",
        "focus_key": "personal",
        "recommended_modes": ["personal", "default"],
    },
]


def _fetch_count(connection_factory, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        with connection_factory() as conn:
            row = conn.execute(sql, params).fetchone()
            return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _safe_provider_status() -> dict:
    resolution = get_provider_resolution()
    return {
        "default_provider": resolution.get("default_provider"),
        "override": resolution.get("override"),
        "effective_provider": resolution.get("effective_provider"),
        "effective_from": resolution.get("effective_from"),
        "default_ok": bool(resolution.get("default_ok")),
        "override_ok": bool(resolution.get("override_ok")),
    }


def _research_status() -> dict:
    configured, _message, provider = validate_research_config()
    return {
        "configured": configured,
        "provider": provider,
    }


def _task_counts(lane: str | None = None) -> dict:
    params: tuple[Any, ...] = ()
    lane_clause = ""
    if lane:
        lane_clause = " AND lane = ?"
        params = (lane,)

    return {
        "pending": _fetch_count(
            get_task_connection,
            f"SELECT COUNT(*) FROM tasks WHERE status = 'pending'{lane_clause}",
            params,
        ),
        "done": _fetch_count(
            get_task_connection,
            f"SELECT COUNT(*) FROM tasks WHERE status = 'done'{lane_clause}",
            params,
        ),
    }


def _memory_count(lane: str | None = None) -> int:
    if lane:
        return _fetch_count(
            get_memory_connection,
            "SELECT COUNT(*) FROM memory_entries WHERE lane = ?",
            (lane,),
        )
    return _fetch_count(get_memory_connection, "SELECT COUNT(*) FROM memory_entries")


def _conversation_count() -> int:
    return _fetch_count(
        get_memory_connection,
        "SELECT COUNT(*) FROM conversation_logs",
    )


def _available_counts(lane: str) -> dict:
    task_counts = _task_counts(lane=lane)
    return {
        "memory": _memory_count(lane=lane),
        "pending_tasks": task_counts["pending"],
        "done_tasks": task_counts["done"],
    }


def _console_task(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "text": item.get("task_text"),
        "task_text": item.get("task_text"),
        "status": item.get("status"),
        "lane": item.get("lane"),
        "source_message": item.get("source_message"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "read_only": True,
    }


def _console_conversation(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "user_message": item.get("user_message"),
        "assistant_response": item.get("assistant_response"),
        "mode": item.get("mode"),
        "provider": item.get("provider"),
        "model": item.get("model"),
        "created_at": item.get("created_at"),
        "memory_used": bool(item.get("memory_used")),
        "read_only": True,
    }


@router.get("/status")
def console_status() -> dict:
    task_counts = _task_counts()
    active_focus = get_active_focus(CONSOLE_USER_ID, CONSOLE_DEFAULT_LANE)
    return {
        "app_name": settings.APP_NAME,
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "mode": get_mode(CONSOLE_USER_ID),
        "focus": active_focus,
        "lane": CONSOLE_DEFAULT_LANE,
        "provider": _safe_provider_status(),
        "research": _research_status(),
        "counts": {
            "memory": _memory_count(),
            "pending_tasks": task_counts["pending"],
            "done_tasks": task_counts["done"],
            "recent_conversations": _conversation_count(),
        },
    }


@router.get("/projects")
def console_projects() -> dict:
    items = []
    for project in PROJECTS:
        focus_key = project["focus_key"]
        items.append(
            {
                **project,
                "mapping": "lightweight_inferred",
                "known_focus": focus_key in VALID_FOCUSES,
                "read_only": True,
                "available_counts": _available_counts(focus_key),
            }
        )

    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "mapping": "lightweight_inferred",
        "items": items,
    }


@router.get("/memory")
def console_memory(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    items = []
    for item in get_memories(user_id=CONSOLE_USER_ID, limit=limit):
        items.append(
            {
                "id": item.get("id"),
                "content": item.get("content"),
                "category": item.get("category"),
                "lane": item.get("lane"),
                "visibility": item.get("visibility"),
                "created_at": item.get("created_at"),
                "read_only": True,
            }
        )

    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "count": len(items),
        "items": items,
    }


@router.get("/tasks")
def console_tasks(limit: int = Query(default=50, ge=1, le=100)) -> dict:
    with get_task_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, task_text, status, lane, source_message, created_at, updated_at
            FROM tasks
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    items = [_console_task(dict(row)) for row in rows]
    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "count": len(items),
        "items": items,
    }


@router.get("/conversations")
def console_conversations(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    items = [
        _console_conversation(item)
        for item in get_recent_conversations(limit=limit)
    ]
    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "count": len(items),
        "items": items,
    }
