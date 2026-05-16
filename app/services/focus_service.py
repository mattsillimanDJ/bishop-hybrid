import sqlite3

from app.services.database_path import DEFAULT_DB_PATH, get_db_path

DB_PATH = DEFAULT_DB_PATH

VALID_FOCUSES = {"stemlab", "work", "dj", "personal", "bishop", "website", "events"}


def normalize_focus(focus: str) -> str:
    return (focus or "").strip().lower()


def init_focus_table() -> None:
    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS active_focuses (
                user_id TEXT NOT NULL,
                lane TEXT NOT NULL,
                focus TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, lane)
            )
            """
        )
        conn.commit()


def get_active_focus(user_id: str, lane: str) -> str | None:
    init_focus_table()

    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        cursor = conn.execute(
            """
            SELECT focus
            FROM active_focuses
            WHERE user_id = ? AND lane = ?
            """,
            (user_id, lane),
        )
        row = cursor.fetchone()

    if not row:
        return None

    focus = normalize_focus(row[0])
    if focus in VALID_FOCUSES:
        return focus

    return None


def set_active_focus(user_id: str, lane: str, focus: str) -> str:
    normalized = normalize_focus(focus)
    if normalized not in VALID_FOCUSES:
        raise ValueError(f"Unsupported focus: {focus}")

    init_focus_table()
    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO active_focuses (user_id, lane, focus, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, lane)
            DO UPDATE SET
                focus = excluded.focus,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, lane, normalized),
        )
        conn.commit()

    return normalized


def clear_active_focus(user_id: str, lane: str) -> bool:
    init_focus_table()

    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM active_focuses
            WHERE user_id = ? AND lane = ?
            """,
            (user_id, lane),
        )
        conn.commit()
        return cursor.rowcount > 0
