from app.services import chat_service, provider_service, provider_state_service


def test_get_effective_provider_uses_override(monkeypatch):
    monkeypatch.setattr(provider_state_service, "get_provider_override", lambda: "claude")
    monkeypatch.setattr(provider_state_service.settings, "LLM_PROVIDER", "openai")

    assert provider_state_service.get_effective_provider() == "claude"


def test_get_effective_provider_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(provider_state_service, "get_provider_override", lambda: None)
    monkeypatch.setattr(provider_state_service.settings, "LLM_PROVIDER", "openai")

    assert provider_state_service.get_effective_provider() == "openai"


def test_generate_text_rejects_unsupported_provider():
    try:
        provider_service.generate_text(
            provider="notreal",
            system_prompt="system",
            user_prompt="user",
        )
        assert False, "Expected ValueError for unsupported provider"
    except ValueError as e:
        assert "Unsupported provider" in str(e)


def test_get_mode_system_prompt_default():
    prompt = chat_service.get_mode_system_prompt("default")
    assert "helpful private AI assistant for Matt" in prompt
    assert "practical" in prompt


def test_get_mode_system_prompt_work():
    prompt = chat_service.get_mode_system_prompt("work")
    assert "work mode" in prompt
    assert "strategic" in prompt
    assert "business value" in prompt


def test_get_mode_system_prompt_personal():
    prompt = chat_service.get_mode_system_prompt("personal")
    assert "personal mode" in prompt
    assert "warm" in prompt
    assert "relationships" in prompt


def test_extract_queries_includes_message_and_keywords():
    queries = chat_service.extract_queries("What do you know about Ben at work?")

    assert "What do you know about Ben at work?" in queries
    assert "Ben" in queries or "ben" in [q.lower() for q in queries]
    assert "work" in [q.lower() for q in queries]


def test_generate_memory_context_returns_no_memory_when_empty(monkeypatch):
    monkeypatch.setattr(chat_service, "search_memories", lambda user_id, query, limit=8: [])

    result = chat_service.generate_memory_context(
        user_id="U123",
        message="Tell me about Ben",
    )

    assert result == "No relevant memory found."


def test_generate_memory_context_deduplicates_matches(monkeypatch):
    def fake_search_memories(user_id, query, limit=8):
        return [
            {"id": 1, "content": "Ben is Matt's son"},
            {"id": 1, "content": "Ben is Matt's son"},
            {"id": 2, "content": "Ben likes business"},
        ]

    monkeypatch.setattr(chat_service, "search_memories", fake_search_memories)

    result = chat_service.generate_memory_context(
        user_id="U123",
        message="Tell me about Ben",
    )

    assert "- Ben is Matt's son" in result
    assert "- Ben likes business" in result
    assert result.count("Ben is Matt's son") == 1


def test_generate_reply_uses_effective_provider(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(chat_service, "generate_memory_context", lambda user_id, message: "Ben is Matt's son")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "claude")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["provider"] = provider
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "test reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(user_id="U123", message="Tell me about Ben")

    assert result == "test reply"
    assert captured["provider"] == "claude"
    assert "work mode" in captured["system_prompt"]
    assert "Ben is Matt's son" in captured["user_prompt"]
    assert "Tell me about Ben" in captured["user_prompt"]
