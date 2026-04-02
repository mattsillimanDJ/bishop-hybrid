import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bishop_memory.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_conversation_log_table() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                platform TEXT NOT NULL,
                user_id TEXT,
                channel_id TEXT,
                session_id TEXT,
                user_message TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                memory_used INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'default',
                provider TEXT NOT NULL DEFAULT 'openai',
                model TEXT,
                metadata TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def log_conversation(
    *,
    platform: str,
    user_id: Optional[str],
    channel_id: Optional[str],
    session_id: Optional[str],
    user_message: str,
    assistant_response: str,
    memory_used: bool = False,
    mode: str = "default",
    provider: str = "openai",
    model: Optional[str] = None,
    metadata: Optional[str] = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO conversation_logs (
                created_at,
                platform,
                user_id,
                channel_id,
                session_id,
                user_message,
                assistant_response,
                memory_used,
                mode,
                provider,
                model,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                platform,
                user_id,
                channel_id,
                session_id,
                user_message,
                assistant_response,
                1 if memory_used else 0,
                mode,
                provider,
                model,
                metadata,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_conversations(limit: int = 20):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                platform,
                user_id,
                channel_id,
                session_id,
                user_message,
                assistant_response,
                memory_used,
                mode,
                provider,
                model,
                metadata
            FROM conversation_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def is_utility_conversation_command(message: str) -> bool:
    lowered = (message or "").strip().lower()

    if lowered in {
        "help",
        "status",
        "show config",
        "show provider",
        "show mode",
        "show recent conversations",
    }:
        return True

    if re.fullmatch(r"show last \d+ conversations", lowered):
        return True

    return False


def get_recent_conversations_for_user(
    *,
    user_id: str,
    limit: int = 5,
    platform: str = "slack",
    exclude_utility_commands: bool = False,
    fetch_limit: Optional[int] = None,
):
    conn = get_connection()
    try:
        db_limit = fetch_limit or limit

        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                platform,
                user_id,
                channel_id,
                session_id,
                user_message,
                assistant_response,
                memory_used,
                mode,
                provider,
                model,
                metadata
            FROM conversation_logs
            WHERE user_id = ?
              AND platform = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, platform, db_limit),
        ).fetchall()

        items = [dict(row) for row in rows]

        if exclude_utility_commands:
            items = [
                item
                for item in items
                if not is_utility_conversation_command(item.get("user_message", ""))
            ]

        return items[:limit]
    finally:
        conn.close()
