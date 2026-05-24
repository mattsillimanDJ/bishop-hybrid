import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.conversation_log_service import get_recent_conversations, log_conversation
from app.services.focus_service import set_active_focus
from app.services.memory_service import add_memory, get_memories
from app.services.mode_service import set_mode
from app.services.task_service import add_task, get_tasks, mark_task_done


client = TestClient(app)


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

    response = client.get("/console/status")

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
    response = client.get("/console/projects")

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

    response = client.get("/console/memory")

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

    response = client.get("/console/tasks")

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

    response = client.get("/console/conversations")

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
        "/console/status",
        "/console/projects",
        "/console/memory",
        "/console/tasks",
        "/console/conversations",
    ]:
        assert client.post(path).status_code == 405
        assert client.put(path).status_code == 405
        assert client.patch(path).status_code == 405
        assert client.delete(path).status_code == 405


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

    assert client.get("/console/status").status_code == 200
    assert client.get("/console/projects").status_code == 200
    assert client.get("/console/memory").status_code == 200
    assert client.get("/console/tasks").status_code == 200
    assert client.get("/console/conversations").status_code == 200

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

    payloads = []
    for path in [
        "/console/status",
        "/console/projects",
        "/console/memory",
        "/console/tasks",
        "/console/conversations",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        payloads.append(json.dumps(response.json()))

    combined = "\n".join(payloads)
    assert "secret-openai-value" not in combined
    assert "secret-anthropic-value" not in combined
    assert "secret-slack-token" not in combined
    assert "secret-slack-signing" not in combined
    assert "secret-research-value" not in combined
    assert "secret-database-url" not in combined
