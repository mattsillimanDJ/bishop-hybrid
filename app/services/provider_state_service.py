import sqlite3
from app.config import settings

DB_PATH = "app/data/bishop_memory.db"


def init_provider_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS provider_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_provider_override():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider FROM provider_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_provider_override(provider: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO provider_state (id, provider)
        VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET provider = excluded.provider
    """, (provider,))
    conn.commit()
    conn.close()


def clear_provider_override():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM provider_state WHERE id = 1")
    conn.commit()
    conn.close()


def get_effective_provider():
    override = get_provider_override()
    if override:
        return override
    return settings.LLM_PROVIDER
