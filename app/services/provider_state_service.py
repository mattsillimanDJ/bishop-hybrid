import sqlite3

from app.config import settings
from app.services.provider_service import VALID_PROVIDERS, validate_provider_config

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
    normalized = (provider or "").strip().lower()

    if normalized not in VALID_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO provider_state (id, provider)
        VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET provider = excluded.provider
    """, (normalized,))
    conn.commit()
    conn.close()


def clear_provider_override():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM provider_state WHERE id = 1")
    conn.commit()
    conn.close()


def get_default_provider():
    default_provider = (settings.LLM_PROVIDER or "openai").strip().lower()
    if default_provider in VALID_PROVIDERS:
        return default_provider
    return "openai"


def is_provider_usable(provider: str) -> tuple[bool, str]:
    normalized = (provider or "").strip().lower()

    if normalized not in VALID_PROVIDERS:
        return False, f"Unsupported provider: {provider}"

    return validate_provider_config(normalized)


def get_effective_provider():
    override = get_provider_override()
    default_provider = get_default_provider()

    if override:
        override = override.strip().lower()

        if override in VALID_PROVIDERS:
            override_ok, _ = is_provider_usable(override)
            if override_ok:
                return override

    default_ok, _ = is_provider_usable(default_provider)
    if default_ok:
        return default_provider

    if default_provider != "openai":
        openai_ok, _ = is_provider_usable("openai")
        if openai_ok:
            return "openai"

    if default_provider != "claude":
        claude_ok, _ = is_provider_usable("claude")
        if claude_ok:
            return "claude"

    return default_provider


def get_provider_resolution() -> dict:
    override = get_provider_override()
    default_provider = get_default_provider()

    cleaned_override = (override or "").strip().lower() or None
    override_ok = False
    override_message = "No override set"

    if cleaned_override:
        if cleaned_override not in VALID_PROVIDERS:
            override_message = f"Unsupported override: {cleaned_override}"
        else:
            override_ok, override_message = is_provider_usable(cleaned_override)

    default_ok, default_message = is_provider_usable(default_provider)
    effective_provider = get_effective_provider()

    return {
        "override": cleaned_override,
        "override_ok": override_ok,
        "override_message": override_message,
        "default_provider": default_provider,
        "default_ok": default_ok,
        "default_message": default_message,
        "effective_provider": effective_provider,
        "effective_from": (
            "override"
            if cleaned_override and cleaned_override == effective_provider and override_ok
            else "default"
        ),
    }
