import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.services.database_path import DEFAULT_DB_PATH, get_db_path


DB_PATH = DEFAULT_DB_PATH

MAX_CONTEXT_TURNS = 6
MAX_MESSAGE_CHARS = 500
MAX_CONTEXT_CHARS = 2400
NO_FOCUS_KEY = "__none__"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_focus_key(focus: Optional[str]) -> str:
    normalized = (focus or "").strip().lower()
    return normalized or NO_FOCUS_KEY


def init_working_session_context_table() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS working_session_contexts (
                user_id TEXT NOT NULL,
                lane TEXT NOT NULL,
                focus TEXT NOT NULL DEFAULT '__none__',
                updated_at TEXT NOT NULL,
                turns_json TEXT NOT NULL,
                PRIMARY KEY (user_id, lane, focus)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def compact_text(value: str, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _load_turns(user_id: str, lane: str, focus: Optional[str]) -> list[dict]:
    init_working_session_context_table()
    focus_key = normalize_focus_key(focus)

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT turns_json
            FROM working_session_contexts
            WHERE user_id = ? AND lane = ? AND focus = ?
            """,
            (user_id, lane, focus_key),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return []

    try:
        turns = json.loads(row["turns_json"])
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(turns, list):
        return []

    safe_turns = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        user_message = compact_text(item.get("user", ""))
        assistant_response = compact_text(item.get("assistant", ""))
        if user_message and assistant_response:
            safe_turns.append(
                {
                    "user": user_message,
                    "assistant": assistant_response,
                }
            )

    return safe_turns[-MAX_CONTEXT_TURNS:]


def append_working_session_turn(
    *,
    user_id: str,
    lane: str,
    focus: Optional[str],
    user_message: str,
    assistant_response: str,
) -> None:
    user_message = compact_text(user_message)
    assistant_response = compact_text(assistant_response)
    if not user_id or not lane or not user_message or not assistant_response:
        return

    focus_key = normalize_focus_key(focus)
    turns = _load_turns(user_id=user_id, lane=lane, focus=focus_key)
    turns.append(
        {
            "user": user_message,
            "assistant": assistant_response,
        }
    )
    turns = turns[-MAX_CONTEXT_TURNS:]

    init_working_session_context_table()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO working_session_contexts (
                user_id,
                lane,
                focus,
                updated_at,
                turns_json
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, lane, focus)
            DO UPDATE SET
                updated_at = excluded.updated_at,
                turns_json = excluded.turns_json
            """,
            (
                user_id,
                lane,
                focus_key,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(turns),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_working_session_context(
    *,
    user_id: str,
    lane: str,
    focus: Optional[str],
) -> str:
    if not user_id or not lane:
        return ""

    turns = _load_turns(user_id=user_id, lane=lane, focus=focus)
    if not turns:
        return ""

    lines = [
        "Recent working session context:",
        "Use this only for short follow-ups like continue, next move, next step, or as you suggested.",
        "Do not treat it as durable memory.",
    ]
    for item in turns:
        lines.append(f"User: {item['user']}")
        lines.append(f"Bishop: {item['assistant']}")

    context = "\n".join(lines)
    if len(context) <= MAX_CONTEXT_CHARS:
        return context
    return context[: MAX_CONTEXT_CHARS - 3].rstrip() + "..."
