from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "bishop_memory.db"

VALID_TASK_STATUSES = {"pending", "done"}
DEFAULT_TASK_DEDUPE_LOOKBACK_LIMIT = 10

EXPLICIT_TASK_PREFIX_PATTERNS = [
    r"^\s*add task\s*[:\-]?\s*",
    r"^\s*save task\s*[:\-]?\s*",
    r"^\s*add this to my list\s*[:\-]?\s*",
    r"^\s*add this to my tasks\s*[:\-]?\s*",
    r"^\s*save this to my list\s*[:\-]?\s*",
    r"^\s*save this\s*[:\-]?\s*",
]

REMINDER_REQUEST_PATTERNS = [
    r"^\s*remind me\b",
    r"^\s*please remind me\b",
    r"^\s*can you remind me\b",
    r"^\s*could you remind me\b",
]


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_task_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                source_message TEXT NOT NULL,
                task_text TEXT NOT NULL,
                assistant_commitment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def normalize_task_text(task_text: str) -> str:
    task_text = (task_text or "").strip().lower()
    task_text = re.sub(r"\s+", " ", task_text)
    task_text = re.sub(r"^[\-\:\,\.\s]+", "", task_text)
    task_text = re.sub(r"[\s\.\!]+$", "", task_text)
    return task_text.strip()


def format_task_text(task_text: str) -> str:
    task_text = (task_text or "").strip()
    task_text = re.sub(r"\s+", " ", task_text)
    task_text = re.sub(r"^[\-\:\,\.\s]+", "", task_text)
    task_text = re.sub(r"[\s\.\!]+$", "", task_text)
    return task_text.strip()


def truncate_task_text(task_text: str, limit: int = 160) -> str:
    task_text = format_task_text(task_text)
    if len(task_text) <= limit:
        return task_text
    return task_text[: limit - 3].rstrip() + "..."


def looks_like_explicit_task_command(message: str) -> bool:
    message = (message or "").strip()
    if not message:
        return False

    lowered = message.lower()
    return any(re.match(pattern, lowered) for pattern in EXPLICIT_TASK_PREFIX_PATTERNS)


def extract_task_text_from_explicit_command(message: str) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()

    for pattern in EXPLICIT_TASK_PREFIX_PATTERNS:
        match = re.match(pattern, lowered)
        if match:
            extracted = original[match.end():].strip()
            extracted = format_task_text(extracted)
            return extracted or None

    return None


def looks_like_reminder_request(message: str) -> bool:
    message = (message or "").strip()
    if not message:
        return False

    lowered = message.lower()
    return any(re.match(pattern, lowered) for pattern in REMINDER_REQUEST_PATTERNS)


def extract_task_text_from_reminder_request(message: str) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()

    if not looks_like_reminder_request(original):
        return None

    to_match = re.search(r"\bto\b", lowered)
    if to_match:
        extracted = original[to_match.end():].strip()
        extracted = format_task_text(extracted)
        return extracted or None

    cleaned = original
    for pattern in REMINDER_REQUEST_PATTERNS:
        match = re.match(pattern, lowered)
        if match:
            cleaned = original[match.end():].strip()
            break

    cleaned = format_task_text(cleaned)
    return cleaned or None


def should_capture_task_from_user_message(message: str) -> bool:
    return looks_like_explicit_task_command(message) or looks_like_reminder_request(message)


def build_task_text_from_user_message(message: str) -> str | None:
    explicit_task_text = extract_task_text_from_explicit_command(message)
    if explicit_task_text:
        return truncate_task_text(explicit_task_text)

    reminder_task_text = extract_task_text_from_reminder_request(message)
    if reminder_task_text:
        return truncate_task_text(reminder_task_text)

    return None


def find_recent_matching_task(
    user_id: str,
    task_text: str,
    *,
    status: str = "pending",
    limit: int = DEFAULT_TASK_DEDUPE_LOOKBACK_LIMIT,
) -> Dict | None:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    normalized_candidate = normalize_task_text(task_text)
    if not normalized_candidate:
        return None

    recent_tasks = get_tasks(user_id=user_id, status=status, limit=limit)
    for task in recent_tasks:
        existing_normalized = normalize_task_text(task.get("task_text", ""))
        if existing_normalized == normalized_candidate:
            return task

    return None


def add_task(
    user_id: str,
    source_message: str,
    task_text: str,
    assistant_commitment: str,
    channel_id: str | None = None,
    session_id: str | None = None,
    status: str = "pending",
    dedupe: bool = True,
) -> Dict:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    init_task_table()

    normalized_task_text = truncate_task_text(task_text)
    if not normalized_task_text:
        raise ValueError("task_text cannot be empty")

    if dedupe:
        existing_task = find_recent_matching_task(
            user_id=user_id,
            task_text=normalized_task_text,
            status=status,
        )
        if existing_task:
            return {
                "id": existing_task["id"],
                "user_id": existing_task["user_id"],
                "channel_id": existing_task["channel_id"],
                "session_id": existing_task["session_id"],
                "status": existing_task["status"],
                "source_message": existing_task["source_message"],
                "task_text": existing_task["task_text"],
                "assistant_commitment": existing_task["assistant_commitment"],
                "created": False,
                "deduped": True,
            }

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (
                user_id,
                channel_id,
                session_id,
                status,
                source_message,
                task_text,
                assistant_commitment,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                user_id,
                channel_id,
                session_id,
                status,
                source_message,
                normalized_task_text,
                assistant_commitment,
            ),
        )
        conn.commit()
        task_id = cursor.lastrowid

    return {
        "id": task_id,
        "user_id": user_id,
        "channel_id": channel_id,
        "session_id": session_id,
        "status": status,
        "source_message": source_message,
        "task_text": normalized_task_text,
        "assistant_commitment": assistant_commitment,
        "created": True,
        "deduped": False,
    }


def get_tasks(user_id: str, status: str | None = None, limit: int = 10) -> List[Dict]:
    init_task_table()

    query = (
        "SELECT id, user_id, channel_id, session_id, status, source_message, "
        "task_text, assistant_commitment, created_at, updated_at "
        "FROM tasks WHERE user_id = ?"
    )
    params: list = [user_id]

    if status:
        if status not in VALID_TASK_STATUSES:
            raise ValueError(f"Invalid task status: {status}")
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def clear_tasks(user_id: str, status: str | None = None) -> Dict:
    init_task_table()

    query = "DELETE FROM tasks WHERE user_id = ?"
    params: list = [user_id]

    if status:
        if status not in VALID_TASK_STATUSES:
            raise ValueError(f"Invalid task status: {status}")
        query += " AND status = ?"
        params.append(status)

    with get_connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        deleted_count = cursor.rowcount

    return {"deleted": deleted_count}
