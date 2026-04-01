import json
import sqlite3
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "bishop_memory.db"
SEED_PATH = BASE_DIR / "data" / "seed_memory.json"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def seed_memory():
    init_db()

    if not SEED_PATH.exists():
        return {"seeded": 0, "message": "No seed file found"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as count FROM memory_entries")
    count = cur.fetchone()["count"]

    if count > 0:
        conn.close()
        return {"seeded": 0, "message": "Memory already exists"}

    with open(SEED_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    inserted = 0
    for item in items:
        cur.execute(
            """
            INSERT INTO memory_entries (user_id, category, content)
            VALUES (?, ?, ?)
            """,
            (item["user_id"], item["category"], item["content"])
        )
        inserted += 1

    conn.commit()
    conn.close()

    return {"seeded": inserted, "message": "Seed memory loaded"}


def get_memories(user_id: str = "matt", limit: int = 20) -> List[Dict]:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, user_id, category, content, created_at
        FROM memory_entries
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit)
    )

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def add_memory(user_id: str, category: str, content: str) -> Dict:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO memory_entries (user_id, category, content)
        VALUES (?, ?, ?)
        """,
        (user_id, category, content)
    )

    conn.commit()
    memory_id = cur.lastrowid
    conn.close()

    return {
        "id": memory_id,
        "user_id": user_id,
        "category": category,
        "content": content,
    }


def search_memories(user_id: str, query: str, limit: int = 10) -> List[Dict]:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    like_query = f"%{query}%"
    cur.execute(
        """
        SELECT id, user_id, category, content, created_at
        FROM memory_entries
        WHERE user_id = ?
          AND LOWER(content) LIKE LOWER(?)
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, like_query, limit)
    )

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def delete_memory_by_query(user_id: str, query: str) -> Dict:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    like_query = f"%{query}%"

    cur.execute(
        """
        SELECT id, content
        FROM memory_entries
        WHERE user_id = ?
          AND LOWER(content) LIKE LOWER(?)
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, like_query)
    )

    row = cur.fetchone()

    if not row:
        conn.close()
        return {"deleted": False, "message": "No matching memory found"}

    cur.execute(
        "DELETE FROM memory_entries WHERE id = ?",
        (row["id"],)
    )

    conn.commit()
    conn.close()

    return {
        "deleted": True,
        "id": row["id"],
        "content": row["content"]
    }
