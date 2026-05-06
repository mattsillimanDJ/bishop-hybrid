import pytest

from app.services.conversation_log_service import init_conversation_log_table
from app.services.focus_service import init_focus_table
from app.services.memory_service import init_db
from app.services.mode_service import init_mode_table
from app.services.provider_state_service import init_provider_table
from app.services.session_context_service import init_working_session_context_table
from app.services.task_service import init_task_table


@pytest.fixture(autouse=True)
def use_isolated_bishop_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BISHOP_DB_PATH", str(tmp_path / "bishop_test.db"))
    init_db()
    init_conversation_log_table()
    init_focus_table()
    init_mode_table()
    init_provider_table()
    init_task_table()
    init_working_session_context_table()
