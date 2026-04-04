# app/services/task_service.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "bishop_memory.db"

VALID_TASK_STATUSES = {"pending", "done"}


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


def add_task(
    user_id: str,
    source_message: str,
    task_text: str,
    assistant_commitment: str,
    channel_id: str | None = None,
    session_id: str | None = None,
    status: str = "pending",
) -> Dict:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    init_task_table()

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
                task_text,
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
        "task_text": task_text,
        "assistant_commitment": assistant_commitment,
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
