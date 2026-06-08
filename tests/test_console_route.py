import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import task_service
from app.services import memory_service
from app.services.conversation_log_service import get_connection as get_conversation_connection
from app.services.conversation_log_service import get_recent_conversations, log_conversation
from app.services.focus_service import clear_active_focus, set_active_focus
from app.services.memory_service import add_memory, get_memories
from app.services.mode_service import set_mode
from app.services.task_service import add_task, get_tasks, mark_task_done


client = TestClient(app)

CONSOLE_TEST_TOKEN = "test-console-token"
CONSOLE_HEADERS = {"X-Bishop-Console-Token": CONSOLE_TEST_TOKEN}
CONSOLE_PATHS = [
    "/console/dashboard",
    "/console/status",
    "/console/projects",
    "/console/next-actions",
    "/console/memory",
    "/console/tasks",
    "/console/conversations",
]


@pytest.fixture(autouse=True)
def configure_console_token(monkeypatch):
    monkeypatch.setattr(settings, "CONSOLE_API_TOKEN", CONSOLE_TEST_TOKEN)


def test_console_routes_reject_missing_token():
    for path in CONSOLE_PATHS:
        response = client.get(path)
        assert response.status_code == 401
        assert response.json() == {"detail": "Console authentication required"}


def test_console_routes_reject_invalid_token():
    headers = {"X-Bishop-Console-Token": "wrong-token"}
    for path in CONSOLE_PATHS:
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Console authentication required"}


def test_console_routes_fail_closed_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "CONSOLE_API_TOKEN", "")
    for path in CONSOLE_PATHS:
        response = client.get(path, headers=CONSOLE_HEADERS)
        assert response.status_code == 401
        assert response.json() == {"detail": "Console authentication required"}


def test_console_routes_allow_valid_token():
    for path in CONSOLE_PATHS:
        response = client.get(path, headers=CONSOLE_HEADERS)
        assert response.status_code == 200
        assert response.json()["read_only"] is True


def test_console_ui_shell_is_served_without_exposing_token():
    for path in ["/console-ui", "/console-ui/"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Bishop Console" in response.text
        assert "Read-only" in response.text
        assert "Refresh" in response.text
        assert "Last refreshed: never" in response.text
        assert "Current Focus" in response.text
        assert "Today Summary" in response.text
        assert CONSOLE_TEST_TOKEN not in response.text


def test_console_ui_assets_are_served_without_exposing_token():
    for path in ["/console-ui/assets/console.css", "/console-ui/assets/console.js"]:
        response = client.get(path)
        assert response.status_code == 200
        assert CONSOLE_TEST_TOKEN not in response.text


def test_console_ui_browser_smoke_contract_for_read_only_interactions():
    page = client.get("/console-ui")
    script = client.get("/console-ui/assets/console.js")

    assert page.status_code == 200
    assert script.status_code == 200
    assert 'id="token-form"' in page.text
    assert 'id="token-input"' in page.text
    assert 'id="refresh-data"' in page.text
    assert 'id="change-token"' in page.text
    assert 'id="clear-token"' in page.text
    assert 'id="last-refreshed"' in page.text
    assert 'id="current-focus"' in page.text
    assert 'id="current-focus-reason"' in page.text
    assert 'id="today-summary"' in page.text
    assert 'id="next-best-action"' in page.text
    assert 'id="changed-today"' in page.text
    assert 'id="attention-projects"' in page.text
    assert 'id="next-actions"' in page.text
    assert 'class="dashboard-grid command-center"' in page.text
    assert 'class="content-grid transparency-grid"' in page.text
    assert 'class="panel raw-panel"' in page.text
    assert page.text.index("What Changed Today") < page.text.index("Pending Task Queue")
    assert "Next Useful Action" in page.text
    assert "Projects Needing Attention" in page.text
    assert "Pending Task Queue" in page.text
    assert "Project Inventory" in page.text
    assert "Today Summary" in page.text
    assert 'src="/console-ui/assets/console.js"' in page.text

    source = script.text
    assert 'const TOKEN_KEY = "bishop.console.token";' in source
    assert 'const authPanel = document.querySelector(".auth-panel");' in source
    assert 'dashboard: "/console/dashboard"' in source
    assert 'nextActions: "/console/next-actions"' in source
    assert "sessionStorage.setItem(TOKEN_KEY, token);" in source
    assert "sessionStorage.removeItem(TOKEN_KEY);" in source
    assert 'authPanel.classList.toggle("authenticated", isCollapsed);' in source
    assert 'changeTokenButton.addEventListener("click"' in source
    assert "projectHealth(project)" in source
    assert 'setText("#current-focus", text(focus.title, "Review the newest task queue."));' in source
    assert 'setText("#today-summary", text(summary.title, "No changes logged today."));' in source
    assert "renderAttentionProjects(data.attention_projects);" in source
    assert "loadConsoleData(storedToken());" in source
    assert "Last refreshed: never" in source
    assert "setLastRefreshed(new Date());" in source
    assert "Promise.all(" in source
    assert "setSectionError(name, `Could not load this section." in source
    assert "Some Console sections could not load. Check section errors." in source

    add_memory("matt", "note", "Console UI smoke memory", lane="matt")
    add_task(
        user_id="matt",
        lane="matt",
        source_message="add task console ui smoke",
        task_text="console ui smoke",
        assistant_commitment="I'll track it.",
    )
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="console ui smoke question",
        assistant_response="console ui smoke answer",
    )

    loaded = {}
    for path in CONSOLE_PATHS:
        response = client.get(path, headers=CONSOLE_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        assert payload["read_only"] is True
        loaded[path] = payload

    assert loaded["/console/status"]["counts"]["memory"] >= 1
    assert loaded["/console/dashboard"]["current_focus"]["title"]
    assert loaded["/console/dashboard"]["today_summary"]["tasks_added"] >= 1
    assert loaded["/console/dashboard"]["next_best_action"]["title"]
    assert any(
        item["type"] == "task" and "console ui smoke" in item["title"]
        for item in loaded["/console/dashboard"]["changed_today"]
    )
    assert any(
        item["content"] == "Console UI smoke memory"
        for item in loaded["/console/memory"]["items"]
    )
    assert any(
        item["task_text"] == "console ui smoke"
        for item in loaded["/console/tasks"]["items"]
    )
    assert any(
        item["title"] == "console ui smoke"
        for item in loaded["/console/next-actions"]["items"]
    )
    assert any(
        item["user_message"] == "console ui smoke question"
        for item in loaded["/console/conversations"]["items"]
    )

    failed_section = client.get("/console/memory")
    still_loaded = client.get("/console/tasks", headers=CONSOLE_HEADERS)

    assert failed_section.status_code == 401
    assert still_loaded.status_code == 200
    assert still_loaded.json()["read_only"] is True


def test_console_dashboard_returns_read_only_operating_briefing():
    set_mode("matt", "work")
    set_active_focus("matt", "matt", "bishop")
    add_memory("matt", "note", "Dashboard should know Bishop console context", lane="bishop")
    add_task(
        user_id="matt",
        lane="bishop",
        source_message="add task brief Matt on Console",
        task_text="brief Matt on Console",
        assistant_commitment="I'll track it.",
    )
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="what changed in the console today",
        assistant_response="Console changed today.",
        memory_used=True,
        mode="work",
        provider="openai",
        model="gpt-test",
    )

    response = client.get("/console/dashboard", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["console_phase"] == "phase_1_read_only"
    assert data["read_only"] is True
    assert data["generated_from"] == "existing_console_data"
    assert data["today_filter"] == "sqlite_date_created_at_equals_date_now"
    assert data["today_filter_timezone"] == "sqlite_database_day_not_user_timezone"
    assert data["mode"] == "work"
    assert data["lane"] == "matt"
    assert data["current_focus"] == {
        "focus": "bishop",
        "title": "Stay on Bishop.",
        "reason": "1 pending task in the active focus.",
        "source": "active_focus",
        "read_only": True,
    }
    assert data["today_summary"]["tasks_added"] == 1
    assert data["today_summary"]["memory_added"] == 1
    assert data["today_summary"]["conversations_logged"] == 1
    assert data["today_summary"]["read_only"] is True
    assert "1 task, 1 memory, 1 conversation logged today." == data["today_summary"]["title"]
    assert {
        "current_focus",
        "today_summary",
        "changed_today",
        "attention_projects",
        "next_best_action",
    }.issubset(data)
    assert any(item["type"] == "task" for item in data["changed_today"])
    assert any(item["type"] == "memory" for item in data["changed_today"])
    assert any(item["type"] == "conversation" for item in data["changed_today"])
    assert data["attention_projects"][0]["id"] == "bishop"
    assert data["attention_projects"][0]["status"] == "Needs attention"
    assert data["attention_projects"][0]["read_only"] is True
    assert data["next_best_action"]["title"] == "Start with: brief Matt on Console"
    assert data["next_best_action"]["source"] == "pending_task"
    assert data["next_best_action"]["read_only"] is True


def test_console_dashboard_today_filter_uses_sqlite_created_at_day_boundary():
    add_task(
        user_id="matt",
        lane="work",
        source_message="add task current dashboard task",
        task_text="current dashboard task",
        assistant_commitment="I'll track it.",
    )
    old_task = add_task(
        user_id="matt",
        lane="work",
        source_message="add task old dashboard task",
        task_text="old dashboard task",
        assistant_commitment="I'll track it.",
    )
    old_memory = add_memory(
        "matt",
        "note",
        "Old dashboard memory",
        lane="work",
    )
    add_memory("matt", "note", "Current dashboard memory", lane="work")
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="current dashboard conversation",
        assistant_response="current response",
    )
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="old dashboard conversation",
        assistant_response="old response",
    )

    old_timestamp = "2001-01-02T03:04:05+00:00"
    with task_service.get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET created_at = ? WHERE id = ?",
            (old_timestamp, old_task["id"]),
        )
        conn.commit()
    with memory_service.get_connection() as conn:
        conn.execute(
            "UPDATE memory_entries SET created_at = ? WHERE id = ?",
            (old_timestamp, old_memory["id"]),
        )
        conn.commit()
    with get_conversation_connection() as conn:
        conn.execute(
            "UPDATE conversation_logs SET created_at = ? WHERE user_message = ?",
            (old_timestamp, "old dashboard conversation"),
        )
        conn.commit()

    response = client.get("/console/dashboard", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["today_summary"]["tasks_added"] == 1
    assert data["today_summary"]["memory_added"] == 1
    assert data["today_summary"]["conversations_logged"] == 1
    changed_titles = [item["title"] for item in data["changed_today"]]
    assert any("current dashboard task" in title for title in changed_titles)
    assert any("Current dashboard memory" in title for title in changed_titles)
    assert any("current dashboard conversation" in title for title in changed_titles)
    assert not any("old dashboard" in title.lower() for title in changed_titles)


def test_console_dashboard_surfaces_general_pending_tasks_as_operations():
    clear_active_focus("matt", "matt")
    task = add_task(
        user_id="matt",
        lane="general",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="I'll track it.",
    )

    response = client.get("/console/dashboard", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["current_focus"] == {
        "focus": "general",
        "title": "Clear the open task queue.",
        "reason": "Newest pending task: review the deck",
        "source": "newest_pending_task",
        "read_only": True,
    }
    assert data["next_best_action"]["title"] == "Start with: review the deck"
    assert data["next_best_action"]["detail"] == (
        "Use the Operations lane; this is the highest-signal pending task."
    )
    assert data["next_best_action"]["lane"] == "general"
    operations = next(
        item for item in data["attention_projects"] if item["id"] == "operations"
    )
    assert operations["name"] == "Operations"
    assert operations["status"] == "Needs attention"
    assert operations["reason"] == "1 pending general task."
    assert operations["counts"]["pending_tasks"] == 1
    assert operations["read_only"] is True
    assert task["id"]
    assert any(
        item["lane"] == "general" and "review the deck" in item["title"]
        for item in data["changed_today"]
        if item["type"] == "task"
    )


def test_console_status_returns_read_only_summary(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "secret-slack-token")
    monkeypatch.setattr(settings, "RESEARCH_API_KEY", "secret-research-key")

    set_mode("matt", "work")
    set_active_focus("matt", "matt", "bishop")
    add_memory("matt", "note", "Console status memory", lane="matt")
    add_task(
        user_id="matt",
        lane="matt",
        source_message="add task review status",
        task_text="review status",
        assistant_commitment="I'll track it.",
    )
    done_task = add_task(
        user_id="matt",
        lane="matt",
        source_message="add task done status",
        task_text="done status",
        assistant_commitment="I'll track it.",
    )
    mark_task_done("matt", done_task["task_text"], lane="matt")
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="hello",
        assistant_response="hi",
        memory_used=True,
        mode="work",
        provider="openai",
        model="gpt-test",
    )

    response = client.get("/console/status", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["app_name"] == settings.APP_NAME
    assert data["console_phase"] == "phase_1_read_only"
    assert data["read_only"] is True
    assert data["mode"] == "work"
    assert data["focus"] == "bishop"
    assert data["lane"] == "matt"
    assert data["provider"]["effective_provider"] in {"openai", "claude"}
    assert "default_provider" in data["provider"]
    assert data["research"]["provider"]
    assert data["counts"]["memory"] >= 1
    assert data["counts"]["pending_tasks"] >= 1
    assert data["counts"]["done_tasks"] >= 1
    assert data["counts"]["recent_conversations"] >= 1
    assert "secret-openai-key" not in json.dumps(data)
    assert "secret-slack-token" not in json.dumps(data)
    assert "secret-research-key" not in json.dumps(data)


def test_console_projects_returns_known_focus_cards():
    response = client.get("/console/projects", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    project_ids = {item["id"] for item in data["items"]}
    assert project_ids == {
        "bishop",
        "stemlab",
        "work",
        "dj",
        "events",
        "website",
        "personal",
    }
    assert data["read_only"] is True
    assert data["mapping"] == "lightweight_inferred"
    assert all(item["read_only"] is True for item in data["items"])
    assert all(item["known_focus"] is True for item in data["items"])
    assert all("available_counts" in item for item in data["items"])


def test_console_memory_returns_existing_memory_only():
    add_memory("matt", "preference", "Console memory item", lane="matt")

    response = client.get("/console/memory", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["read_only"] is True
    assert data["count"] >= 1
    assert data["items"][0]["read_only"] is True
    assert {
        "id",
        "content",
        "category",
        "lane",
        "visibility",
        "created_at",
        "read_only",
    }.issubset(data["items"][0])
    assert any(item["content"] == "Console memory item" for item in data["items"])


def test_console_tasks_returns_existing_tasks_only():
    add_task(
        user_id="matt",
        lane="work",
        source_message="add task write console test",
        task_text="write console test",
        assistant_commitment="I'll track it.",
    )

    response = client.get("/console/tasks", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["read_only"] is True
    assert data["count"] >= 1
    item = data["items"][0]
    assert item["read_only"] is True
    assert {
        "id",
        "text",
        "task_text",
        "status",
        "lane",
        "source_message",
        "created_at",
        "updated_at",
        "read_only",
    }.issubset(item)
    assert any(item["task_text"] == "write console test" for item in data["items"])


def test_console_next_actions_returns_pending_tasks_only_newest_first():
    older = add_task(
        user_id="matt",
        lane="work",
        source_message="add task older next move",
        task_text="older next move",
        assistant_commitment="I'll track it.",
    )
    newer = add_task(
        user_id="matt",
        lane="bishop",
        source_message="add task newer next move",
        task_text="newer next move",
        assistant_commitment="I'll track it.",
    )
    done = add_task(
        user_id="matt",
        lane="work",
        source_message="add task completed next move",
        task_text="completed next move",
        assistant_commitment="I'll track it.",
    )
    mark_task_done("matt", done["task_text"], lane="work")

    response = client.get("/console/next-actions", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["console_phase"] == "phase_1_read_only"
    assert data["read_only"] is True
    assert data["strategy"] == "pending_tasks_newest_first"
    assert data["schema_limited"] is False
    assert data["count"] == 2
    assert [item["title"] for item in data["items"]] == [
        newer["task_text"],
        older["task_text"],
    ]
    assert all(item["read_only"] is True for item in data["items"])
    assert all(item["title"] != done["task_text"] for item in data["items"])
    assert data["items"][0]["lane"] == "bishop"
    assert data["items"][0]["source_message"] == "add task newer next move"
    assert data["items"][0]["created_at"]


def test_console_task_endpoints_support_legacy_task_schema_without_lane():
    with task_service.get_connection() as conn:
        conn.execute("DROP TABLE tasks")
        conn.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source_message TEXT NOT NULL,
                task_text TEXT NOT NULL,
                assistant_commitment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tasks (
                user_id,
                status,
                source_message,
                task_text,
                assistant_commitment
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "matt",
                "pending",
                "legacy source",
                "legacy task without lane",
                "I'll track it.",
            ),
        )
        conn.commit()
        before_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, user_id, status, source_message, task_text, assistant_commitment, created_at FROM tasks"
            ).fetchall()
        ]

    responses = {
        path: client.get(path, headers=CONSOLE_HEADERS)
        for path in [
            "/console/dashboard",
            "/console/tasks",
            "/console/next-actions",
            "/console/status",
            "/console/projects",
        ]
    }

    for response in responses.values():
        assert response.status_code == 200
        assert response.json()["read_only"] is True
        assert "no such column" not in json.dumps(response.json()).lower()

    task_payload = responses["/console/tasks"].json()
    assert task_payload["schema_limited"] is True
    assert task_payload["items"][0]["task_text"] == "legacy task without lane"
    assert task_payload["items"][0]["lane"] is None
    assert task_payload["items"][0]["updated_at"] is None
    assert task_payload["items"][0]["schema_limited"] is True

    next_actions_payload = responses["/console/next-actions"].json()
    assert next_actions_payload["schema_limited"] is True
    assert next_actions_payload["items"][0]["title"] == "legacy task without lane"
    assert next_actions_payload["items"][0]["lane"] == "unknown"
    assert next_actions_payload["items"][0]["read_only"] is True

    status_payload = responses["/console/status"].json()
    assert status_payload["counts"]["pending_tasks"] >= 1

    projects_payload = responses["/console/projects"].json()
    assert all(
        item["available_counts"]["task_schema_limited"] is True
        for item in projects_payload["items"]
    )

    with task_service.get_connection() as conn:
        after_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, user_id, status, source_message, task_text, assistant_commitment, created_at FROM tasks"
            ).fetchall()
        ]

    assert after_rows == before_rows


def test_console_next_actions_fails_safely_without_required_task_columns():
    with task_service.get_connection() as conn:
        conn.execute("DROP TABLE tasks")
        conn.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source_message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tasks (user_id, source_message)
            VALUES (?, ?)
            """,
            ("matt", "legacy source without status and task text"),
        )
        conn.commit()
        before_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, user_id, source_message, created_at FROM tasks"
            ).fetchall()
        ]

    response = client.get("/console/next-actions", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "console_phase": "phase_1_read_only",
        "read_only": True,
        "strategy": "pending_tasks_newest_first",
        "schema_limited": True,
        "count": 0,
        "items": [],
    }

    with task_service.get_connection() as conn:
        after_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, user_id, source_message, created_at FROM tasks"
            ).fetchall()
        ]

    assert after_rows == before_rows


def test_console_conversations_returns_existing_conversations_only():
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="console conversation question",
        assistant_response="console conversation answer",
        memory_used=True,
        mode="work",
        provider="openai",
        model="gpt-test",
    )

    response = client.get("/console/conversations", headers=CONSOLE_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["read_only"] is True
    assert data["count"] >= 1
    item = data["items"][0]
    assert item["read_only"] is True
    assert {
        "id",
        "user_message",
        "assistant_response",
        "mode",
        "provider",
        "model",
        "created_at",
        "memory_used",
        "read_only",
    }.issubset(item)
    assert any(
        item["user_message"] == "console conversation question"
        for item in data["items"]
    )


def test_console_routes_do_not_allow_write_methods():
    for path in [
        "/console/dashboard",
        "/console/status",
        "/console/projects",
        "/console/next-actions",
        "/console/memory",
        "/console/tasks",
        "/console/conversations",
    ]:
        assert client.post(path).status_code == 405
        assert client.put(path).status_code == 405
        assert client.patch(path).status_code == 405
        assert client.delete(path).status_code == 405


def test_console_namespace_has_no_write_routes():
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    console_routes = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith(("/console", "/console-ui"))
    ]

    assert console_routes
    assert all(
        not (set(getattr(route, "methods", set()) or set()) & write_methods)
        for route in console_routes
    )


def test_console_reads_do_not_mutate_memory_tasks_or_conversations():
    add_memory("matt", "note", "Do not mutate this memory", lane="matt")
    task = add_task(
        user_id="matt",
        lane="matt",
        source_message="add task do not mutate",
        task_text="do not mutate",
        assistant_commitment="I'll track it.",
    )
    log_conversation(
        platform="slack",
        user_id="matt",
        channel_id="C123",
        session_id="S123",
        user_message="do not mutate conversation",
        assistant_response="not mutating",
    )

    before_memory = get_memories(user_id="matt", limit=100)
    before_pending_tasks = get_tasks(user_id="matt", lane="matt", status="pending", limit=100)
    before_done_tasks = get_tasks(user_id="matt", lane="matt", status="done", limit=100)
    before_conversations = get_recent_conversations(limit=100)

    assert client.get("/console/status", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/dashboard", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/projects", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/next-actions", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/memory", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/tasks", headers=CONSOLE_HEADERS).status_code == 200
    assert client.get("/console/conversations", headers=CONSOLE_HEADERS).status_code == 200

    after_memory = get_memories(user_id="matt", limit=100)
    after_pending_tasks = get_tasks(user_id="matt", lane="matt", status="pending", limit=100)
    after_done_tasks = get_tasks(user_id="matt", lane="matt", status="done", limit=100)
    after_conversations = get_recent_conversations(limit=100)

    assert before_memory == after_memory
    assert before_pending_tasks == after_pending_tasks
    assert before_done_tasks == after_done_tasks
    assert before_conversations == after_conversations
    assert any(item["id"] == task["id"] for item in after_pending_tasks)


def test_console_endpoints_do_not_expose_secret_values(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "secret-openai-value")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "secret-anthropic-value")
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "secret-slack-token")
    monkeypatch.setattr(settings, "SLACK_SIGNING_SECRET", "secret-slack-signing")
    monkeypatch.setattr(settings, "RESEARCH_API_KEY", "secret-research-value")
    monkeypatch.setattr(settings, "DATABASE_URL", "secret-database-url")
    monkeypatch.setattr(settings, "CONSOLE_API_TOKEN", "secret-console-token")

    payloads = []
    headers = {"X-Bishop-Console-Token": "secret-console-token"}
    for path in CONSOLE_PATHS:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        payloads.append(json.dumps(response.json()))

    combined = "\n".join(payloads)
    assert "secret-openai-value" not in combined
    assert "secret-anthropic-value" not in combined
    assert "secret-slack-token" not in combined
    assert "secret-slack-signing" not in combined
    assert "secret-research-value" not in combined
    assert "secret-database-url" not in combined
    assert "secret-console-token" not in combined
