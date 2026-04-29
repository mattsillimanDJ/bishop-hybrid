from app.services import research_service


def test_research_service_unavailable_without_provider(monkeypatch):
    monkeypatch.setattr(research_service.settings, "RESEARCH_PROVIDER", "none")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_KEY", "")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_URL", "")

    available, message, provider = research_service.validate_research_config()
    result = research_service.run_web_research("AI stem separation for Ableton")

    assert available is False
    assert provider == "none"
    assert message == "RESEARCH_PROVIDER is not configured"
    assert result["available"] is False
    assert result["query"] == "AI stem separation for Ableton"
    assert result["missing_configuration"] == "RESEARCH_PROVIDER is not configured"


def test_research_service_unavailable_without_api_key(monkeypatch):
    monkeypatch.setattr(research_service.settings, "RESEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_KEY", "")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_URL", "")

    available, message, provider = research_service.validate_research_config()

    assert available is False
    assert provider == "tavily"
    assert message == "RESEARCH_API_KEY is not set"


def test_research_service_available_with_mocked_provider(monkeypatch):
    monkeypatch.setattr(research_service.settings, "RESEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_KEY", "test-key")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_URL", "")

    def fake_search_provider(query, limit=5):
        assert query == "Ableton stem workflow"
        assert limit == 5
        return [
            {
                "title": "Ableton workflow source",
                "url": "https://example.com/ableton",
                "snippet": "Producers care about clean labels, tempo, and usable clips.",
            }
        ]

    monkeypatch.setattr(research_service, "search_provider", fake_search_provider)

    result = research_service.run_web_research("Ableton stem workflow", stemlab=True)

    assert result["available"] is True
    assert result["provider"] == "tavily"
    assert result["query"] == "Ableton stem workflow"
    assert result["sources"][0]["url"] == "https://example.com/ableton"
    assert "Producers care about clean labels" in result["findings"][0]
    assert result["confidence"] == "medium"
    assert result["suggested_memory_item"]
