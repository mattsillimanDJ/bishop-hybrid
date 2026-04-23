import json
import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional

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
            owner_user_id TEXT DEFAULT 'matt',
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            lane TEXT DEFAULT 'matt',
            visibility TEXT DEFAULT 'private',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        cur.execute("ALTER TABLE memory_entries ADD COLUMN lane TEXT DEFAULT 'matt'")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE memory_entries ADD COLUMN visibility TEXT DEFAULT 'private'")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE memory_entries ADD COLUMN owner_user_id TEXT DEFAULT 'matt'")
    except Exception:
        pass

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
            INSERT INTO memory_entries
            (user_id, owner_user_id, category, content, lane, visibility)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["user_id"],
                item.get("owner_user_id", item["user_id"]),
                item["category"],
                item["content"],
                item.get("lane", "matt"),
                item.get("visibility", "private"),
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()

    return {"seeded": inserted, "message": "Seed memory loaded"}


def _visibility_clause(user_id: str, lane: Optional[str]):
    """
    Shared-lane visibility rules:
    - private: owner only, lane-specific when lane is provided
    - shared: visible to all users in the same lane
    - global: visible to everyone
    """
    if lane:
        return (
            """
            (
                (visibility = 'private' AND owner_user_id = ? AND lane = ?)
                OR (visibility = 'shared' AND lane = ?)
                OR (visibility = 'global')
            )
            """,
            (user_id, lane, lane),
        )

    return (
        """
        (
            (visibility = 'private' AND owner_user_id = ?)
            OR (visibility = 'global')
        )
        """,
        (user_id,),
    )


def get_memories(
    user_id: str = "matt",
    lane: Optional[str] = None,
    limit: int = 20,
) -> List[Dict]:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    clause, params = _visibility_clause(user_id, lane)

    sql = f"""
        SELECT id, user_id, owner_user_id, category, content, lane, visibility, created_at
        FROM memory_entries
        WHERE {clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """

    cur.execute(sql, (*params, limit))
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def _normalize_for_dedupe(content: str) -> str:
    return (content or "").strip().casefold()


_GENERIC_CATEGORIES = {"", "note"}

_PREFERENCE_PATTERNS = (
    re.compile(r"\bprefer(s|red|ring)?\b", re.IGNORECASE),
    re.compile(r"\bpreferences?\b", re.IGNORECASE),
    re.compile(r"\bwants?\s+(bishop|you|me)\s+to\b", re.IGNORECASE),
    re.compile(
        r"\balways\s+(use|avoid|keep|remember|start|end|respond|reply|check|confirm|prefer|skip|ask)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnever\s+(use|avoid|skip|assume|guess|reply|respond|suggest|mock|commit|push)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(don'?t|do not)\s+(ever|use|reply|respond|ask|assume|guess|suggest|mock|commit|push)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bshould\s+(always|never)\b", re.IGNORECASE),
)

_PROFILE_PATTERNS = (
    re.compile(r"\b(user'?s?|my|matt'?s?|his|her)\s+name\s+is\b", re.IGNORECASE),
    re.compile(
        r"\b(is|am)\s+(a|an)\s+"
        r"(advertising|marketing|software|product|engineer|executive|director|"
        r"manager|developer|designer|consultant|dj|musician|founder|ceo|cto|"
        r"vp|head|lead|president|senior|junior|principal|staff|chief|owner|"
        r"partner|analyst|architect|writer|author|teacher|student|doctor|"
        r"lawyer|nurse|artist|researcher|scientist|operator)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(is|are)\s+(matt'?s?|my)\s+"
        r"(wife|husband|son|daughter|partner|mom|dad|father|mother|brother|"
        r"sister|kid|child|boss|manager|teammate|coworker|colleague|friend|"
        r"family|spouse)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(my|matt'?s?)\s+"
        r"(wife|husband|son|daughter|partner|mom|dad|father|mother|brother|"
        r"sister|kid|child|family|spouse)\s+(is|was|works|lives)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(lives|based|born|grew\s+up)\s+in\b", re.IGNORECASE),
    re.compile(r"\bworks\s+(at|as|for)\b", re.IGNORECASE),
)


def infer_memory_category(content: str, category: str) -> str:
    """Upgrade a generic (blank or 'note') category to 'preference' or 'profile'
    when the content reads like durable operator guidance or stable identity.
    Any explicit non-generic category is preserved as-is.
    """
    current = (category or "").strip().lower()
    if current not in _GENERIC_CATEGORIES:
        return category

    text = (content or "").strip()
    if not text:
        return "note"

    for pattern in _PREFERENCE_PATTERNS:
        if pattern.search(text):
            return "preference"

    for pattern in _PROFILE_PATTERNS:
        if pattern.search(text):
            return "profile"

    return "note"


def add_memory(
    user_id: str,
    category: str,
    content: str,
    lane: str = "matt",
    visibility: str = "private",
) -> Dict:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    category = infer_memory_category(content, category)

    new_norm = _normalize_for_dedupe(content)

    superseded_ids: List[int] = []
    if new_norm:
        cur.execute(
            """
            SELECT id, user_id, owner_user_id, category, content, lane, visibility
            FROM memory_entries
            WHERE owner_user_id = ? AND lane = ? AND visibility = ?
            """,
            (user_id, lane, visibility),
        )
        existing_rows = cur.fetchall()

        for row in existing_rows:
            existing_norm = _normalize_for_dedupe(row["content"])
            if not existing_norm:
                continue
            if existing_norm == new_norm or (
                len(new_norm) < len(existing_norm)
                and (
                    existing_norm.startswith(new_norm)
                    or existing_norm.endswith(new_norm)
                )
            ):
                conn.close()
                return {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "owner_user_id": row["owner_user_id"],
                    "category": row["category"],
                    "content": row["content"],
                    "lane": row["lane"],
                    "visibility": row["visibility"],
                }

        for row in existing_rows:
            existing_norm = _normalize_for_dedupe(row["content"])
            if not existing_norm:
                continue
            if len(existing_norm) < len(new_norm) and (
                new_norm.startswith(existing_norm)
                or new_norm.endswith(existing_norm)
            ):
                superseded_ids.append(row["id"])

        if superseded_ids:
            placeholders = ",".join("?" for _ in superseded_ids)
            cur.execute(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
                superseded_ids,
            )

    cur.execute(
        """
        INSERT INTO memory_entries
        (user_id, owner_user_id, category, content, lane, visibility)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, user_id, category, content, lane, visibility),
    )

    conn.commit()
    memory_id = cur.lastrowid
    conn.close()

    return {
        "id": memory_id,
        "user_id": user_id,
        "owner_user_id": user_id,
        "category": category,
        "content": content,
        "lane": lane,
        "visibility": visibility,
    }


def search_memories(
    user_id: str,
    query: str,
    lane: Optional[str] = None,
    limit: int = 10,
) -> List[Dict]:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    like_query = f"%{query}%"
    clause, params = _visibility_clause(user_id, lane)

    sql = f"""
        SELECT id, user_id, owner_user_id, category, content, lane, visibility, created_at
        FROM memory_entries
        WHERE LOWER(content) LIKE LOWER(?)
          AND {clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """

    cur.execute(sql, (like_query, *params, limit))
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def delete_memory_by_query(
    user_id: str,
    query: str,
    lane: Optional[str] = None,
) -> Dict:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    like_query = f"%{query}%"

    if lane:
        cur.execute(
            """
            SELECT id, content, lane, visibility, owner_user_id
            FROM memory_entries
            WHERE owner_user_id = ?
              AND lane = ?
              AND LOWER(content) LIKE LOWER(?)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, lane, like_query),
        )
    else:
        cur.execute(
            """
            SELECT id, content, lane, visibility, owner_user_id
            FROM memory_entries
            WHERE owner_user_id = ?
              AND LOWER(content) LIKE LOWER(?)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, like_query),
        )

    row = cur.fetchone()

    if not row:
        conn.close()
        return {"deleted": False, "message": "No matching memory found"}

    cur.execute("DELETE FROM memory_entries WHERE id = ?", (row["id"],))

    conn.commit()
    conn.close()

    return {
        "deleted": True,
        "id": row["id"],
        "content": row["content"],
        "lane": row["lane"],
        "visibility": row["visibility"],
        "owner_user_id": row["owner_user_id"],
    }


def cleanup_duplicate_memories(dry_run: bool = False) -> Dict:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, owner_user_id, lane, visibility, content
        FROM memory_entries
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    groups: Dict[tuple, List[Dict]] = {}
    for row in rows:
        key = (row["owner_user_id"], row["lane"], row["visibility"])
        groups.setdefault(key, []).append(
            {
                "id": row["id"],
                "content": row["content"],
                "norm": _normalize_for_dedupe(row["content"]),
            }
        )

    deleted_ids: List[int] = []
    deleted_details: List[Dict] = []

    for key, members in groups.items():
        to_delete: set = set()

        by_norm: Dict[str, List[Dict]] = {}
        for member in members:
            if not member["norm"]:
                continue
            by_norm.setdefault(member["norm"], []).append(member)

        for _norm, siblings in by_norm.items():
            if len(siblings) < 2:
                continue
            siblings_sorted = sorted(siblings, key=lambda m: m["id"])
            for loser in siblings_sorted[1:]:
                to_delete.add(loser["id"])

        survivors = [m for m in members if m["id"] not in to_delete and m["norm"]]

        for candidate in survivors:
            c_norm = candidate["norm"]
            for other in survivors:
                if other["id"] == candidate["id"]:
                    continue
                o_norm = other["norm"]
                if len(c_norm) < len(o_norm) and (
                    o_norm.startswith(c_norm) or o_norm.endswith(c_norm)
                ):
                    to_delete.add(candidate["id"])
                    break

        for member in members:
            if member["id"] in to_delete:
                deleted_ids.append(member["id"])
                deleted_details.append(
                    {
                        "id": member["id"],
                        "owner_user_id": key[0],
                        "lane": key[1],
                        "visibility": key[2],
                        "content": member["content"],
                    }
                )

    if deleted_ids and not dry_run:
        placeholders = ",".join("?" for _ in deleted_ids)
        cur.execute(
            f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
            deleted_ids,
        )
        conn.commit()

    conn.close()

    return {
        "scanned": len(rows),
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "deleted_details": deleted_details,
        "dry_run": dry_run,
    }
