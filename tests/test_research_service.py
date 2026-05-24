import pytest

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
    assert result["research_shape"] == "stemlab"
    assert "public web/search results only" in result["access_limits"]
    assert "snippets are treated as snippets, not full article reads" in result["access_limits"]
    assert "no automatic memory save" in result["access_limits"]
    assert result["sources"][0]["url"] == "https://example.com/ableton"
    assert "Producers care about clean labels" in result["findings"][0]
    assert result["confidence"] == "medium"
    assert "No memory was saved" in result["suggested_memory_item"]


def test_research_service_bishop_shape_uses_self_improvement_next_queries(monkeypatch):
    monkeypatch.setattr(research_service.settings, "RESEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_KEY", "test-key")
    monkeypatch.setattr(research_service.settings, "RESEARCH_API_URL", "")

    def fake_search_provider(query, limit=5):
        assert query == "LangGraph Slack memory agent patterns"
        return [
            {
                "title": "Agent pattern source",
                "url": "https://example.com/agent-pattern",
                "snippet": "Public snippet about Slack agent memory tradeoffs.",
            }
        ]

    monkeypatch.setattr(research_service, "search_provider", fake_search_provider)

    result = research_service.run_web_research("LangGraph Slack memory agent patterns", bishop=True)

    assert result["available"] is True
    assert result["research_shape"] == "bishop_self_improvement"
    assert result["bishop"] is True
    assert result["stemlab"] is False
    assert "no paywall bypass" in result["access_limits"]
    assert "small, safe Bishop improvement" in result["product_implications"][0]
    assert "LangGraph Slack memory agent patterns official docs" in result["suggested_next_queries"]


def test_research_service_dedupes_sources_by_normalized_url_and_title():
    result = research_service.build_research_result(
        "LangGraph memory patterns",
        [
            {
                "title": "LangGraph Memory Docs",
                "url": "https://langchain-ai.github.io/langgraph/concepts/memory/?utm_source=test",
                "snippet": "Primary docs snippet.",
            },
            {
                "title": "LangGraph Memory Docs",
                "url": "https://langchain-ai.github.io/langgraph/concepts/memory/",
                "snippet": "Duplicate docs snippet.",
            },
            {
                "title": "DeepWiki LangGraph",
                "url": "https://deepwiki.com/langchain-ai/langgraph",
                "snippet": "Mirror-style summary snippet.",
            },
        ],
        "tavily",
        bishop=True,
    )

    assert len(result["sources"]) == 2
    assert result["sources"][0]["title"] == "LangGraph Memory Docs"
    assert result["sources"][0]["source_quality"] == "credible technical article"
    assert result["sources"][1]["source_quality"] == "mirror/summary-looking source"
    assert "mirror or summary-looking source should be verified against the original source" in result["weak_signals"]


def test_research_service_bishop_prefers_primary_sources_over_forums_and_courses():
    result = research_service.build_research_result(
        "Slack agent memory patterns",
        [
            {
                "title": "Forum thread about agents",
                "url": "https://community.example.com/agents",
                "snippet": "Forum users discuss memory patterns.",
            },
            {
                "title": "Slack platform docs",
                "url": "https://api.slack.com/apis",
                "snippet": "Official Slack platform documentation.",
            },
            {
                "title": "Agent memory course",
                "url": "https://example.com/course/agent-memory",
                "snippet": "Buy this course for agent memory lessons.",
            },
            {
                "title": "LangGraph repository",
                "url": "https://github.com/langchain-ai/langgraph",
                "snippet": "Repository source.",
            },
        ],
        "tavily",
        bishop=True,
    )

    assert [source["source_quality"] for source in result["sources"][:2]] == [
        "GitHub/repository source",
        "primary framework/vendor docs",
    ]
    assert "repository/source-code source present" in result["evidence_quality"]
    assert "primary framework/vendor docs present" in result["evidence_quality"]
    assert "course or sales-looking source should be verified against docs or repositories" in result["weak_signals"]


def test_research_service_builds_repeated_speed_pattern():
    result = research_service.build_research_result(
        "stem separation speed",
        [
            {
                "title": "Fast stem processing",
                "url": "https://example.com/one",
                "snippet": "This tool is fast for short clips.",
            },
            {
                "title": "Slow export report",
                "url": "https://example.com/two",
                "snippet": "Processing time can be slow on large songs.",
            },
        ],
        "tavily",
    )

    assert "Multiple sources mention speed or processing time." in result["repeated_patterns"]


def test_research_service_zero_sources_evidence_quality_is_not_single_source():
    result = research_service.build_research_result(
        "narrow query with no results",
        [],
        "tavily",
    )

    assert (
        "no sources returned; retry with a broader query or different source target"
        in result["evidence_quality"]
    )
    assert "single-source claims need verification" not in result["evidence_quality"]


def test_research_service_one_source_evidence_quality_needs_verification():
    result = research_service.build_research_result(
        "single source query",
        [
            {
                "title": "Only source",
                "url": "https://example.com/source",
                "snippet": "One source-backed snippet.",
            }
        ],
        "tavily",
    )

    assert "single-source claims need verification" in result["evidence_quality"]


def test_research_service_identifies_official_ableton_source():
    result = research_service.build_research_result(
        "Ableton warp help",
        [
            {
                "title": "Ableton Help",
                "url": "https://help.ableton.com/hc/en-us/articles/example",
                "snippet": "Official help article.",
            }
        ],
        "tavily",
    )

    assert "primary/official source present" in result["evidence_quality"]
    assert "official docs/help: 1 source" in result["source_types"]


def test_research_service_identifies_reddit_community_source_type():
    result = research_service.build_research_result(
        "StemLab complaints",
        [
            {
                "title": "Reddit discussion",
                "url": "https://www.reddit.com/r/ableton/comments/example",
                "snippet": "Users discuss reliability issues.",
            }
        ],
        "tavily",
    )

    assert "community discussion: 1 source" in result["source_types"]
    assert "forum/user report present" in result["evidence_quality"]


def test_research_service_identifies_x_dot_com_as_social_forum():
    source = {
        "title": "X post",
        "url": "https://x.com/example",
        "snippet": "A social post.",
    }

    assert research_service.classify_source(source) == "social/forum"


def test_research_service_does_not_identify_linux_dot_com_as_social_forum():
    source = {
        "title": "Linux article",
        "url": "https://linux.com/example",
        "snippet": "A normal source.",
    }

    assert research_service.classify_source(source) != "social/forum"


def test_research_service_identifies_twitter_dot_com_as_social_forum():
    source = {
        "title": "Twitter post",
        "url": "https://twitter.com/example",
        "snippet": "A social post.",
    }

    assert research_service.classify_source(source) == "social/forum"


@pytest.mark.parametrize(
    ("url", "expected_type"),
    [
        ("https://reddit.com/r/ableton", "community discussion"),
        ("https://old.reddit.com/r/ableton", "community discussion"),
        ("https://youtube.com/watch?v=abc", "video/tutorial"),
        ("https://music.youtube.com/watch?v=abc", "video/tutorial"),
        ("https://youtu.be/abc", "video/tutorial"),
    ],
)
def test_research_service_known_domains_use_boundary_matching(url, expected_type):
    source = {
        "title": "Known source",
        "url": url,
        "snippet": "A source snippet.",
    }

    assert research_service.classify_source(source) == expected_type


@pytest.mark.parametrize(
    ("url", "unexpected_type"),
    [
        ("https://notreddit.com/example", "community discussion"),
        ("https://youtube.com.example.org/video", "video/tutorial"),
        ("https://fake-youtu.be.example.org/abc", "video/tutorial"),
    ],
)
def test_research_service_known_domain_lookalikes_do_not_match(url, unexpected_type):
    source = {
        "title": "Lookalike source",
        "url": url,
        "snippet": "A source snippet.",
    }

    assert research_service.classify_source(source) != unexpected_type


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
