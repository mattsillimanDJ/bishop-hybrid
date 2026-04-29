import sqlite3

from app.services.database_path import DEFAULT_DB_PATH, get_db_path

DB_PATH = DEFAULT_DB_PATH

VALID_MODES = {"default", "work", "personal", "website", "cmo", "stemlab", "product"}


def init_mode_table() -> None:
    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_modes (
                user_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL DEFAULT 'default',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_mode(user_id: str) -> str:
    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        cursor = conn.execute(
            "SELECT mode FROM user_modes WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()

    if row and row[0] in VALID_MODES:
        return row[0]

    return "default"


def set_mode(user_id: str, mode: str) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}")

    with sqlite3.connect(get_db_path(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO user_modes (user_id, mode, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id)
            DO UPDATE SET
                mode = excluded.mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, mode),
        )
        conn.commit()

    return mode
