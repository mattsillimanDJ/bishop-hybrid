import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "bishop_memory.db"
DB_PATH_ENV_VAR = "BISHOP_DB_PATH"


def resolve_db_path(configured_path: str | Path | None = None) -> Path:
    path = Path(configured_path) if configured_path is not None else DEFAULT_DB_PATH

    if path == DEFAULT_DB_PATH:
        env_path = os.getenv(DB_PATH_ENV_VAR)
        if env_path:
            return Path(env_path).expanduser()

    return path


def ensure_db_parent(db_path: str | Path) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path(configured_path: str | Path | None = None) -> Path:
    return ensure_db_parent(resolve_db_path(configured_path))
