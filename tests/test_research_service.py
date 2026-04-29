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


def test_tavily_request_uses_bearer_header_without_api_key_body(monkeypatch):
    monkeypatch.setattr(research_service.settings, "RESEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_KEY", "tvly-test-key")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_URL", "")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Source",
                        "url": "https://example.com/source",
                        "content": "Evidence snippet.",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers or {}
            return FakeResponse()

    monkeypatch.setattr(research_service.httpx, "Client", FakeClient)

    sources = research_service.search_provider("Ableton stems", limit=3)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["timeout"] <= 5.0
    assert captured["headers"] == {"Authorization": "Bearer tvly-test-key"}
    assert "api_key" not in captured["json"]
    assert captured["json"]["query"] == "Ableton stems"
    assert captured["json"]["max_results"] == 3
    assert sources[0]["url"] == "https://example.com/source"
