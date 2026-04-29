from typing import Any

import httpx

from app.config import settings


VALID_RESEARCH_PROVIDERS = {"tavily", "brave", "serper"}
RESEARCH_PROVIDER_TIMEOUT_SECONDS = 5.0

DEFAULT_RESEARCH_API_URLS = {
    "tavily": "https://api.tavily.com/search",
    "brave": "https://api.search.brave.com/res/v1/web/search",
    "serper": "https://google.serper.dev/search",
}


def normalize_research_provider(provider: str | None = None) -> str:
    return (provider or settings.RESEARCH_PROVIDER or "none").strip().lower() or "none"


def get_research_api_url(provider: str) -> str:
    configured_url = (settings.RESEARCH_API_URL or "").strip()
    if configured_url:
        return configured_url
    return DEFAULT_RESEARCH_API_URLS.get(provider, "")


def validate_research_config() -> tuple[bool, str, str]:
    provider = normalize_research_provider()

    if provider in {"", "none", "off", "disabled"}:
        return False, "RESEARCH_PROVIDER is not configured", provider

    if provider not in VALID_RESEARCH_PROVIDERS:
        return False, f"Unsupported research provider: {provider}", provider

    if not settings.RESEARCH_API_KEY:
        return False, "RESEARCH_API_KEY is not set", provider

    if not get_research_api_url(provider):
        return False, "RESEARCH_API_URL is not set", provider

    return True, f"Live web research is configured through {provider}.", provider


def is_live_research_available() -> bool:
    available, _message, _provider = validate_research_config()
    return available


def build_unavailable_research_result(query: str, *, stemlab: bool = False) -> dict:
    _available, message, provider = validate_research_config()
    setup_step = (
        "Set RESEARCH_PROVIDER to tavily, brave, or serper and set RESEARCH_API_KEY "
        "in the Railway environment."
    )
    return {
        "available": False,
        "provider": provider,
        "query": clean_query(query),
        "missing_configuration": message,
        "next_setup_step": setup_step,
        "stemlab": stemlab,
    }


def clean_query(query: str) -> str:
    return " ".join((query or "").strip().split())


def source_from_item(title: object, url: object, snippet: object) -> dict | None:
    clean_url = str(url or "").strip()
    clean_title = str(title or "").strip()
    clean_snippet = str(snippet or "").strip()
    if not clean_url:
        return None
    return {
        "title": clean_title or clean_url,
        "url": clean_url,
        "snippet": clean_snippet,
    }


def parse_tavily_sources(payload: dict[str, Any]) -> list[dict]:
    sources = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        source = source_from_item(
            item.get("title"),
            item.get("url"),
            item.get("content") or item.get("snippet"),
        )
        if source:
            sources.append(source)
    return sources


def parse_brave_sources(payload: dict[str, Any]) -> list[dict]:
    sources = []
    web_payload = payload.get("web") or {}
    if not isinstance(web_payload, dict):
        return sources
    for item in web_payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        source = source_from_item(
            item.get("title"),
            item.get("url"),
            item.get("description"),
        )
        if source:
            sources.append(source)
    return sources


def parse_serper_sources(payload: dict[str, Any]) -> list[dict]:
    sources = []
    for item in payload.get("organic", []) or []:
        if not isinstance(item, dict):
            continue
        source = source_from_item(
            item.get("title"),
            item.get("link"),
            item.get("snippet"),
        )
        if source:
            sources.append(source)
    return sources


def parse_provider_sources(provider: str, payload: dict[str, Any]) -> list[dict]:
    if provider == "tavily":
        return parse_tavily_sources(payload)
    if provider == "brave":
        return parse_brave_sources(payload)
    if provider == "serper":
        return parse_serper_sources(payload)
    return []


def search_provider(query: str, *, limit: int = 5) -> list[dict]:
    provider = normalize_research_provider()
    api_url = get_research_api_url(provider)

    with httpx.Client(timeout=RESEARCH_PROVIDER_TIMEOUT_SECONDS) as client:
        if provider == "tavily":
            response = client.post(
                api_url,
                json={
                    "query": query,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                    "max_results": limit,
                },
                headers={"Authorization": f"Bearer {settings.RESEARCH_API_KEY}"},
            )
        elif provider == "brave":
            response = client.get(
                api_url,
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": settings.RESEARCH_API_KEY},
            )
        elif provider == "serper":
            response = client.post(
                api_url,
                json={"q": query, "num": limit},
                headers={"X-API-KEY": settings.RESEARCH_API_KEY},
            )
        else:
            return []

        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        return []

    return parse_provider_sources(provider, payload)[:limit]


def build_findings_from_sources(sources: list[dict]) -> list[str]:
    findings = []
    for source in sources:
        title = str(source.get("title") or "").strip()
        snippet = str(source.get("snippet") or "").strip()
        if snippet:
            findings.append(f"{title}: {snippet}" if title else snippet)
        elif title:
            findings.append(f"{title}: source found, needs closer review.")
    return findings


def build_research_result(query: str, sources: list[dict], provider: str, *, stemlab: bool = False) -> dict:
    findings = build_findings_from_sources(sources)
    if sources and findings:
        confidence = "medium"
        open_questions = [
            "Which source claims are repeated across independent sources?",
            "Which findings need primary-source confirmation before saving to memory?",
        ]
    else:
        confidence = "low"
        findings = ["No source-backed findings were returned by the configured search provider."]
        open_questions = ["Is the query too narrow, or did the provider return no useful sources?"]

    product_implications = [
        "Use source-backed evidence only for product or strategy decisions.",
        "Do not save a memory item until a specific source supports the finding.",
    ]

    if stemlab:
        product_implications.insert(
            0,
            "Evaluate whether the evidence changes StemLab workflow, export, quality, or positioning decisions.",
        )

    return {
        "available": True,
        "provider": provider,
        "query": query,
        "sources": sources,
        "findings": findings,
        "confidence": confidence,
        "product_implications": product_implications,
        "open_questions": open_questions,
        "suggested_memory_item": (
            "Only save after selecting a specific source and writing the finding in source-backed format."
        ),
        "stemlab": stemlab,
    }


def run_web_research(query: str, *, stemlab: bool = False, limit: int = 5) -> dict:
    cleaned_query = clean_query(query)
    available, message, provider = validate_research_config()
    if not cleaned_query:
        result = build_unavailable_research_result(cleaned_query, stemlab=stemlab)
        result["missing_configuration"] = "No research query was provided"
        return result

    if not available:
        return build_unavailable_research_result(cleaned_query, stemlab=stemlab)

    try:
        sources = search_provider(cleaned_query, limit=limit)
    except Exception as exc:
        return {
            "available": False,
            "provider": provider,
            "query": cleaned_query,
            "missing_configuration": f"Research provider request failed: {str(exc)}",
            "next_setup_step": "Check RESEARCH_PROVIDER, RESEARCH_API_KEY, RESEARCH_API_URL, and provider access.",
            "stemlab": stemlab,
        }

    return build_research_result(cleaned_query, sources, provider, stemlab=stemlab)
