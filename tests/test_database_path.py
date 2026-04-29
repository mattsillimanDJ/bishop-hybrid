from pathlib import Path

from app.services.database_path import DEFAULT_DB_PATH, get_db_path, resolve_db_path


def test_default_db_path_resolves_to_existing_app_data_location(monkeypatch):
    monkeypatch.delenv("BISHOP_DB_PATH", raising=False)

    assert resolve_db_path(DEFAULT_DB_PATH) == DEFAULT_DB_PATH


def test_bishop_db_path_overrides_default(monkeypatch, tmp_path):
    production_path = tmp_path / "volume" / "bishop_memory.db"
    monkeypatch.setenv("BISHOP_DB_PATH", str(production_path))

    assert resolve_db_path(DEFAULT_DB_PATH) == production_path


def test_get_db_path_creates_parent_directory(monkeypatch, tmp_path):
    db_path = tmp_path / "missing" / "nested" / "bishop_memory.db"
    monkeypatch.setenv("BISHOP_DB_PATH", str(db_path))

    resolved_path = get_db_path(DEFAULT_DB_PATH)

    assert resolved_path == db_path
    assert db_path.parent.exists()


def test_explicit_db_path_is_preserved_for_tests(monkeypatch, tmp_path):
    test_path = tmp_path / "isolated" / "test_bishop_memory.db"
    monkeypatch.setenv("BISHOP_DB_PATH", str(tmp_path / "production.db"))

    assert resolve_db_path(test_path) == test_path
