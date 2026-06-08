import hmac
import sqlite3
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status

from app.config import settings
from app.services.conversation_log_service import get_recent_conversations
from app.services.focus_service import VALID_FOCUSES, get_active_focus
from app.services.focus_service import set_active_focus
from app.services.memory_service import get_connection as get_memory_connection
from app.services.memory_service import add_memory
from app.services.memory_service import get_memories
from app.services.mode_service import get_mode
from app.services.provider_state_service import get_provider_resolution
from app.services.research_service import validate_research_config
from app.services.task_service import add_task
from app.services.task_service import get_connection as get_task_connection


CONSOLE_PHASE = "phase_1_read_only"
CONSOLE_USER_ID = "matt"
CONSOLE_DEFAULT_LANE = "matt"
CONSOLE_AUTH_ERROR = "Console authentication required"
CONSOLE_TASK_FIELDS = (
    "id",
    "task_text",
    "status",
    "lane",
    "source_message",
    "created_at",
    "updated_at",
)
CONSOLE_NEXT_ACTION_FIELDS = (
    "id",
    "lane",
    "task_text",
    "source_message",
    "created_at",
)
CONSOLE_DASHBOARD_TASK_FIELDS = (
    "id",
    "lane",
    "status",
    "task_text",
    "source_message",
    "created_at",
)
CONSOLE_DASHBOARD_MEMORY_FIELDS = (
    "id",
    "category",
    "content",
    "lane",
    "visibility",
    "created_at",
)
CONSOLE_DASHBOARD_CONVERSATION_FIELDS = (
    "id",
    "user_message",
    "assistant_response",
    "mode",
    "provider",
    "created_at",
)
CONSOLE_GENERAL_LANE = "general"


def require_console_auth(
    x_bishop_console_token: str | None = Header(default=None),
) -> None:
    configured_token = settings.CONSOLE_API_TOKEN
    if not configured_token or not x_bishop_console_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=CONSOLE_AUTH_ERROR,
        )

    if not hmac.compare_digest(x_bishop_console_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=CONSOLE_AUTH_ERROR,
        )


router = APIRouter(
    prefix="/console",
    tags=["console"],
    dependencies=[Depends(require_console_auth)],
)

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
CONSOLE_CAPTURE_LANES = tuple(
    sorted({CONSOLE_GENERAL_LANE, *(project["focus_key"] for project in PROJECTS)})
)


def _fetch_count(connection_factory, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        with connection_factory() as conn:
            row = conn.execute(sql, params).fetchone()
            return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


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
    try:
        with get_task_connection() as conn:
            columns = _table_columns(conn, "tasks")
            schema_limited = not columns or "status" not in columns
            lane_clause = ""
            params: tuple[Any, ...] = ()

            if lane:
                if "lane" in columns:
                    lane_clause = " AND lane = ?"
                    params = (lane,)
                else:
                    schema_limited = True
                    return {
                        "pending": 0,
                        "done": 0,
                        "schema_limited": schema_limited,
                    }

            pending = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE status = 'pending'{lane_clause}",
                params,
            ).fetchone()
            done = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE status = 'done'{lane_clause}",
                params,
            ).fetchone()
            return {
                "pending": int(pending[0] or 0) if pending else 0,
                "done": int(done[0] or 0) if done else 0,
                "schema_limited": schema_limited,
            }
    except sqlite3.Error:
        return {"pending": 0, "done": 0, "schema_limited": True}


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
        "task_schema_limited": task_counts["schema_limited"],
    }


def _project_name(focus_key: str | None) -> str:
    if focus_key == CONSOLE_GENERAL_LANE:
        return "Operations"
    for project in PROJECTS:
        if project["focus_key"] == focus_key:
            return project["name"]
    return "Operations"


def _brief_text(value: str | None, fallback: str, limit: int = 140) -> str:
    normalized = " ".join((value or "").split())
    if not normalized:
        return fallback
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _row_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _payload_value(payload: dict[str, Any] | None, key: str) -> str:
    if not payload:
        return ""
    value = payload.get(key)
    return " ".join(str(value or "").split())


def _validated_capture_lane(payload: dict[str, Any] | None) -> str:
    lane = _payload_value(payload, "lane") or CONSOLE_GENERAL_LANE
    normalized = lane.lower()
    if normalized not in CONSOLE_CAPTURE_LANES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a valid Console lane.",
        )
    return normalized


def _order_by_for_columns(columns: set[str]) -> str:
    if "created_at" in columns and "id" in columns:
        return "created_at DESC, id DESC"
    if "created_at" in columns:
        return "created_at DESC"
    if "id" in columns:
        return "id DESC"
    return "ROWID DESC"


def _today_where_clause(column: str = "created_at") -> str:
    # SQLite date() keeps this read-only dashboard simple and deterministic.
    # It follows the database clock/UTC day, so it is not a timezone-aware boundary.
    return f"date({column}) = date('now')"


def _task_rows(
    *,
    limit: int,
    status: str | None = None,
    lane: str | None = None,
    today_only: bool = False,
) -> tuple[list[dict], bool]:
    try:
        with get_task_connection() as conn:
            columns = _table_columns(conn, "tasks")
            selected_columns = [
                column for column in CONSOLE_DASHBOARD_TASK_FIELDS if column in columns
            ]
            schema_limited = any(
                column not in columns for column in CONSOLE_DASHBOARD_TASK_FIELDS
            )

            if "task_text" not in columns or not selected_columns:
                return [], True

            clauses = []
            params: list[Any] = []

            if status:
                if "status" not in columns:
                    return [], True
                clauses.append("status = ?")
                params.append(status)

            if lane:
                if "lane" not in columns:
                    return [], True
                clauses.append("lane = ?")
                params.append(lane)

            if today_only:
                if "created_at" not in columns:
                    return [], True
                clauses.append(_today_where_clause())

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT {", ".join(selected_columns)}
                FROM tasks
                {where}
                ORDER BY {_order_by_for_columns(columns)}
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

        return _row_dicts(rows), schema_limited
    except sqlite3.Error:
        return [], True


def _memory_rows(*, limit: int, lane: str | None = None, today_only: bool = False) -> list[dict]:
    try:
        with get_memory_connection() as conn:
            clauses = []
            params: list[Any] = []
            if lane:
                clauses.append("lane = ?")
                params.append(lane)
            if today_only:
                clauses.append(_today_where_clause())

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT {", ".join(CONSOLE_DASHBOARD_MEMORY_FIELDS)}
                FROM memory_entries
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return _row_dicts(rows)
    except sqlite3.Error:
        return []


def _conversation_rows(*, limit: int, today_only: bool = False) -> list[dict]:
    try:
        with get_memory_connection() as conn:
            where = f"WHERE {_today_where_clause()}" if today_only else ""
            rows = conn.execute(
                f"""
                SELECT {", ".join(CONSOLE_DASHBOARD_CONVERSATION_FIELDS)}
                FROM conversation_logs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return _row_dicts(rows)
    except sqlite3.Error:
        return []


def _today_count(connection_factory, table_name: str) -> int:
    return _fetch_count(
        connection_factory,
        f"SELECT COUNT(*) FROM {table_name} WHERE {_today_where_clause()}",
    )


def _today_task_count() -> tuple[int, bool]:
    try:
        with get_task_connection() as conn:
            columns = _table_columns(conn, "tasks")
            if "created_at" not in columns:
                return 0, True
            row = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE {_today_where_clause()}"
            ).fetchone()
            return int(row[0] or 0) if row else 0, False
    except sqlite3.Error:
        return 0, True


def _today_memory_count(lane: str | None = None) -> int:
    if lane:
        return _fetch_count(
            get_memory_connection,
            f"""
            SELECT COUNT(*)
            FROM memory_entries
            WHERE lane = ? AND {_today_where_clause()}
            """,
            (lane,),
        )
    return _today_count(get_memory_connection, "memory_entries")


def _build_changed_today(
    today_tasks: list[dict],
    today_memories: list[dict],
    today_conversations: list[dict],
) -> list[dict]:
    items = []

    for task in today_tasks[:3]:
        items.append(
            {
                "type": "task",
                "title": f"Task captured: {_brief_text(task.get('task_text'), 'Untitled task')}",
                "detail": f"{_project_name(task.get('lane'))} queue",
                "lane": task.get("lane"),
                "created_at": task.get("created_at"),
                "read_only": True,
            }
        )

    for memory in today_memories[:3]:
        items.append(
            {
                "type": "memory",
                "title": f"Memory added: {_brief_text(memory.get('content'), 'New context')}",
                "detail": f"{_project_name(memory.get('lane'))} context",
                "lane": memory.get("lane"),
                "created_at": memory.get("created_at"),
                "read_only": True,
            }
        )

    for conversation in today_conversations[:3]:
        items.append(
            {
                "type": "conversation",
                "title": f"Conversation logged: {_brief_text(conversation.get('user_message'), 'Recent exchange')}",
                "detail": f"Mode {conversation.get('mode') or 'default'}",
                "lane": None,
                "created_at": conversation.get("created_at"),
                "read_only": True,
            }
        )

    return sorted(
        items,
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )[:6]


def _build_attention_projects() -> list[dict]:
    items = []
    general_counts = _available_counts(CONSOLE_GENERAL_LANE)
    general_pending_tasks = general_counts["pending_tasks"]
    general_today_memory = _today_memory_count(CONSOLE_GENERAL_LANE)

    if (
        general_pending_tasks
        or general_today_memory
        or general_counts["task_schema_limited"]
    ):
        if general_counts["task_schema_limited"]:
            status_label = "Task data limited"
            reason = "Task schema is limited, so Bishop can only use general work context."
        elif general_pending_tasks:
            status_label = "Needs attention"
            reason = f"{general_pending_tasks} pending general task{'s' if general_pending_tasks != 1 else ''}."
        else:
            status_label = "Changed today"
            reason = f"{general_today_memory} new general memory item{'s' if general_today_memory != 1 else ''} today."

        items.append(
            {
                "id": "operations",
                "name": "Operations",
                "focus_key": CONSOLE_GENERAL_LANE,
                "status": status_label,
                "reason": reason,
                "score": (
                    (general_pending_tasks * 3)
                    + (general_today_memory * 2)
                    + general_counts["memory"]
                ),
                "counts": {
                    "pending_tasks": general_pending_tasks,
                    "done_tasks": general_counts["done_tasks"],
                    "memory": general_counts["memory"],
                    "today_memory": general_today_memory,
                    "task_schema_limited": general_counts["task_schema_limited"],
                },
                "read_only": True,
            }
        )

    for project in PROJECTS:
        lane = project["focus_key"]
        counts = _available_counts(lane)
        today_memory = _today_memory_count(lane)
        pending_tasks = counts["pending_tasks"]
        score = (pending_tasks * 3) + (today_memory * 2) + counts["memory"]

        if counts["task_schema_limited"]:
            status_label = "Task data limited"
            reason = "Task schema is limited, so Bishop can only use memory context."
        elif pending_tasks:
            status_label = "Needs attention"
            reason = f"{pending_tasks} pending task{'s' if pending_tasks != 1 else ''} in this lane."
        elif today_memory:
            status_label = "Changed today"
            reason = f"{today_memory} new memory item{'s' if today_memory != 1 else ''} today."
        elif counts["memory"]:
            status_label = "Context ready"
            reason = "Context exists, but there is no pending task."
        else:
            status_label = "Quiet"
            reason = "No pending tasks or saved context yet."

        items.append(
            {
                "id": project["id"],
                "name": project["name"],
                "focus_key": lane,
                "status": status_label,
                "reason": reason,
                "score": score,
                "counts": {
                    "pending_tasks": pending_tasks,
                    "done_tasks": counts["done_tasks"],
                    "memory": counts["memory"],
                    "today_memory": today_memory,
                    "task_schema_limited": counts["task_schema_limited"],
                },
                "read_only": True,
            }
        )

    return sorted(
        items,
        key=lambda item: (
            item["counts"]["task_schema_limited"] is False,
            item["score"],
            item["counts"]["pending_tasks"],
            item["counts"]["today_memory"],
        ),
        reverse=True,
    )[:4]


def _build_current_focus(active_focus: str | None, pending_tasks: list[dict], attention_projects: list[dict]) -> dict:
    if active_focus:
        focus_tasks = [task for task in pending_tasks if task.get("lane") == active_focus]
        task_count = len(focus_tasks)
        return {
            "focus": active_focus,
            "title": f"Stay on {_project_name(active_focus)}.",
            "reason": (
                f"{task_count} pending task{'s' if task_count != 1 else ''} in the active focus."
                if task_count
                else "This is Matt's active focus; define the next concrete task if the queue is empty."
            ),
            "source": "active_focus",
            "read_only": True,
        }

    for task in pending_tasks:
        lane = task.get("lane")
        if lane in VALID_FOCUSES:
            return {
                "focus": lane,
                "title": f"Focus on {_project_name(lane)} next.",
                "reason": f"Newest pending task: {_brief_text(task.get('task_text'), 'Untitled task')}",
                "source": "newest_pending_task",
                "read_only": True,
            }

    if pending_tasks:
        task = pending_tasks[0]
        return {
            "focus": task.get("lane"),
            "title": "Clear the open task queue.",
            "reason": f"Newest pending task: {_brief_text(task.get('task_text'), 'Untitled task')}",
            "source": "newest_pending_task",
            "read_only": True,
        }

    for project in attention_projects:
        if project["score"] > 0:
            return {
                "focus": project["focus_key"],
                "title": f"Review {_project_name(project['focus_key'])}.",
                "reason": project["reason"],
                "source": "project_activity",
                "read_only": True,
            }

    return {
        "focus": None,
        "title": "Review the newest task queue.",
        "reason": "No active focus is set and no project is currently pressing.",
        "source": "fallback",
        "read_only": True,
    }


def _build_next_best_action(current_focus: dict, pending_tasks: list[dict], changed_today: list[dict]) -> dict:
    focus = current_focus.get("focus")
    focus_tasks = [task for task in pending_tasks if task.get("lane") == focus]
    task = focus_tasks[0] if focus_tasks else (pending_tasks[0] if pending_tasks else None)
    if task:
        return {
            "title": f"Start with: {_brief_text(task.get('task_text'), 'Untitled task')}",
            "detail": f"Use the {_project_name(task.get('lane'))} lane; this is the highest-signal pending task.",
            "lane": task.get("lane"),
            "source": "pending_task",
            "created_at": task.get("created_at"),
            "read_only": True,
        }

    if changed_today:
        change = changed_today[0]
        return {
            "title": "Turn today's newest change into a concrete next task.",
            "detail": change["title"],
            "lane": change.get("lane"),
            "source": "today_change",
            "created_at": change.get("created_at"),
            "read_only": True,
        }

    return {
        "title": "Set a concrete focus for Matt's next work block.",
        "detail": "No pending tasks or same-day changes are available in the Console data.",
        "lane": None,
        "source": "fallback",
        "created_at": None,
        "read_only": True,
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
        "schema_limited": bool(item.get("schema_limited")),
        "read_only": True,
    }


def _console_next_action(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "lane": item.get("lane") or "unknown",
        "title": item.get("task_text"),
        "source_message": item.get("source_message"),
        "created_at": item.get("created_at"),
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


@router.get("/dashboard")
def console_dashboard() -> dict:
    active_focus = get_active_focus(CONSOLE_USER_ID, CONSOLE_DEFAULT_LANE)
    pending_tasks, task_schema_limited = _task_rows(limit=25, status="pending")
    today_tasks, today_task_schema_limited = _task_rows(limit=10, today_only=True)
    today_memories = _memory_rows(limit=10, today_only=True)
    today_conversations = _conversation_rows(limit=10, today_only=True)
    today_task_count, today_count_schema_limited = _today_task_count()
    today_memory_count = _today_memory_count()
    today_conversation_count = _today_count(
        get_memory_connection,
        "conversation_logs",
    )
    changed_today = _build_changed_today(
        today_tasks,
        today_memories,
        today_conversations,
    )
    attention_projects = _build_attention_projects()
    current_focus = _build_current_focus(
        active_focus,
        pending_tasks,
        attention_projects,
    )
    next_best_action = _build_next_best_action(
        current_focus,
        pending_tasks,
        changed_today,
    )

    return {
        "app_name": settings.APP_NAME,
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "generated_from": "existing_console_data",
        "today_filter": "sqlite_date_created_at_equals_date_now",
        "today_filter_timezone": "sqlite_database_day_not_user_timezone",
        "mode": get_mode(CONSOLE_USER_ID),
        "lane": CONSOLE_DEFAULT_LANE,
        "provider": _safe_provider_status(),
        "current_focus": current_focus,
        "today_summary": {
            "title": (
                f"{today_task_count} task{'s' if today_task_count != 1 else ''}, "
                f"{today_memory_count} memor{'ies' if today_memory_count != 1 else 'y'}, "
                f"{today_conversation_count} conversation{'s' if today_conversation_count != 1 else ''} logged today."
            ),
            "tasks_added": today_task_count,
            "memory_added": today_memory_count,
            "conversations_logged": today_conversation_count,
            "task_schema_limited": today_task_schema_limited or today_count_schema_limited,
            "read_only": True,
        },
        "changed_today": changed_today,
        "attention_projects": attention_projects,
        "next_best_action": next_best_action,
        "schema_limited": {
            "tasks": task_schema_limited,
            "today_tasks": today_task_schema_limited or today_count_schema_limited,
        },
    }


@router.get("/next-actions")
def console_next_actions(limit: int = Query(default=10, ge=1, le=25)) -> dict:
    with get_task_connection() as conn:
        columns = _table_columns(conn, "tasks")
        selected_columns = [
            column for column in CONSOLE_NEXT_ACTION_FIELDS if column in columns
        ]
        schema_limited = any(
            column not in columns for column in CONSOLE_NEXT_ACTION_FIELDS
        )

        if "status" not in columns or "task_text" not in columns:
            return {
                "console_phase": CONSOLE_PHASE,
                "read_only": True,
                "strategy": "pending_tasks_newest_first",
                "schema_limited": True,
                "count": 0,
                "items": [],
            }

        if "created_at" in columns and "id" in columns:
            order_by = "created_at DESC, id DESC"
        elif "created_at" in columns:
            order_by = "created_at DESC"
        elif "id" in columns:
            order_by = "id DESC"
        else:
            order_by = "ROWID DESC"

        rows = conn.execute(
            f"""
            SELECT {", ".join(selected_columns)}
            FROM tasks
            WHERE status = 'pending'
            ORDER BY {order_by}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    items = [_console_next_action(dict(row)) for row in rows]
    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "strategy": "pending_tasks_newest_first",
        "schema_limited": schema_limited,
        "count": len(items),
        "items": items,
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
            "task_schema_limited": task_counts["schema_limited"],
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


@router.post("/tasks")
def console_add_task(payload: dict[str, Any] | None = Body(default=None)) -> dict:
    task_text = _payload_value(payload, "task_text") or _payload_value(payload, "text")
    if not task_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task text is required.",
        )

    lane = _validated_capture_lane(payload)
    task = add_task(
        user_id=CONSOLE_USER_ID,
        lane=lane,
        source_message=f"Console capture: {task_text}",
        task_text=task_text,
        assistant_commitment="Captured from Bishop Console.",
    )
    return {
        "console_phase": CONSOLE_PHASE,
        "action": "task_added",
        "message": (
            "Task already existed in this lane."
            if task.get("deduped")
            else "Task captured."
        ),
        "created": bool(task.get("created")),
        "deduped": bool(task.get("deduped")),
        "item": {
            "id": task.get("id"),
            "task_text": task.get("task_text"),
            "status": task.get("status"),
            "lane": task.get("lane"),
        },
    }


@router.post("/memory")
def console_add_memory(payload: dict[str, Any] | None = Body(default=None)) -> dict:
    content = _payload_value(payload, "content")
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Memory content is required.",
        )

    lane = _validated_capture_lane(payload)
    memory = add_memory(
        user_id=CONSOLE_USER_ID,
        category="note",
        content=content,
        lane=lane,
        visibility="private",
    )
    skipped = bool(memory.get("skipped"))
    return {
        "console_phase": CONSOLE_PHASE,
        "action": "memory_added",
        "message": (
            "Memory was not saved because it looked like basic identity clutter."
            if skipped
            else "Memory captured."
        ),
        "skipped": skipped,
        "item": {
            "id": memory.get("id"),
            "category": memory.get("category"),
            "content": memory.get("content"),
            "lane": memory.get("lane"),
            "visibility": memory.get("visibility"),
        },
    }


@router.post("/focus")
def console_set_focus(payload: dict[str, Any] | None = Body(default=None)) -> dict:
    focus = _payload_value(payload, "focus").lower()
    if focus not in VALID_FOCUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a valid Console focus.",
        )

    active_focus = set_active_focus(CONSOLE_USER_ID, CONSOLE_DEFAULT_LANE, focus)
    return {
        "console_phase": CONSOLE_PHASE,
        "action": "focus_set",
        "message": f"Focus set to {_project_name(active_focus)}.",
        "focus": active_focus,
        "lane": CONSOLE_DEFAULT_LANE,
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
        columns = _table_columns(conn, "tasks")
        selected_columns = [
            column for column in CONSOLE_TASK_FIELDS if column in columns
        ]
        schema_limited = any(
            column not in columns for column in CONSOLE_TASK_FIELDS
        )
        if "created_at" in columns and "id" in columns:
            order_by = "created_at DESC, id DESC"
        elif "created_at" in columns:
            order_by = "created_at DESC"
        elif "id" in columns:
            order_by = "id DESC"
        else:
            order_by = "ROWID DESC"

        if not selected_columns:
            return {
                "console_phase": CONSOLE_PHASE,
                "read_only": True,
                "schema_limited": True,
                "count": 0,
                "items": [],
            }

        rows = conn.execute(
            f"""
            SELECT {", ".join(selected_columns)}
            FROM tasks
            ORDER BY {order_by}
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    items = [
        _console_task({**dict(row), "schema_limited": schema_limited})
        for row in rows
    ]
    return {
        "console_phase": CONSOLE_PHASE,
        "read_only": True,
        "schema_limited": schema_limited,
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
