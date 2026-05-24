import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings


VALID_RESEARCH_PROVIDERS = {"tavily", "brave", "serper"}
RESEARCH_PROVIDER_TIMEOUT_SECONDS = 5.0
RESEARCH_ACCESS_LIMITS = [
    "public web/search results only",
    "no login-only content accessed",
    "no paywall bypass",
    "no protected previews accessed",
    "snippets are treated as snippets, not full article reads",
    "no automatic memory save",
]

DEFAULT_RESEARCH_API_URLS = {
    "tavily": "https://api.tavily.com/search",
    "brave": "https://api.search.brave.com/res/v1/web/search",
    "serper": "https://google.serper.dev/search",
}

RESEARCH_THEMES = [
    (
        "speed / processing time",
        re.compile(r"\b(speed|fast|faster|slow|slower|processing time|process|render time|wait)\b", re.I),
        "Multiple sources mention speed or processing time.",
    ),
    (
        "quality / artifacts",
        re.compile(r"\b(quality|artifact|artifacts|bleed|clean|separation|stems?|noise)\b", re.I),
        "Multiple sources mention quality or artifacts.",
    ),
    (
        "Ableton workflow / integration",
        re.compile(r"\b(ableton|live set|session view|arrangement|clip|workflow|export)\b", re.I),
        "Multiple sources mention Ableton workflow or integration.",
    ),
    (
        "BPM / warping / timing",
        re.compile(r"\b(bpm|tempo|warp|warping|timing|transient|grid|beat)\b", re.I),
        "Multiple sources mention BPM, warping, or timing.",
    ),
    (
        "metadata / labeling",
        re.compile(r"\b(metadata|label|labels|labeling|tag|tags|key|filename|naming)\b", re.I),
        "Multiple sources mention metadata or labeling.",
    ),
    (
        "CPU / GPU / system requirements",
        re.compile(r"\b(cpu|gpu|system requirements|memory|ram|processor|hardware|performance)\b", re.I),
        "Multiple sources mention CPU, GPU, or system requirements.",
    ),
    (
        "complaints / reliability",
        re.compile(r"\b(complaint|complaints|bug|bugs|crash|crashes|reliable|reliability|issue|issues|problem|problems)\b", re.I),
        "Multiple sources mention complaints or reliability.",
    ),
]


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


def research_shape(*, stemlab: bool = False, bishop: bool = False) -> str:
    if stemlab:
        return "stemlab"
    if bishop:
        return "bishop_self_improvement"
    return "general"


def build_unavailable_research_result(query: str, *, stemlab: bool = False, bishop: bool = False) -> dict:
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
        "research_shape": research_shape(stemlab=stemlab, bishop=bishop),
        "access_limits": RESEARCH_ACCESS_LIMITS,
        "stemlab": stemlab,
        "bishop": bishop,
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


def source_host(source: dict) -> str:
    parsed = urlparse(str(source.get("url") or ""))
    return parsed.netloc.lower().removeprefix("www.")


def host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def source_text(source: dict) -> str:
    return " ".join(
        [
            str(source.get("title") or ""),
            str(source.get("snippet") or ""),
            str(source.get("url") or ""),
        ]
    ).lower()


def classify_source(source: dict) -> str:
    host = source_host(source)
    text = source_text(source)
    is_x_or_twitter = host_matches(host, "x.com") or host_matches(host, "twitter.com")
    is_facebook = host_matches(host, "facebook.com")

    if host_matches(host, "ableton.com"):
        return "official docs/help"
    if host_matches(host, "reddit.com"):
        return "community discussion"
    if host_matches(host, "youtube.com") or host_matches(host, "youtu.be"):
        return "video/tutorial"
    if is_x_or_twitter or is_facebook or any(marker in host for marker in ["forum", "community"]):
        return "social/forum"
    if any(marker in text for marker in ["tutorial", "course", "lesson", "how to", "music school"]):
        return "video/tutorial"
    if any(marker in text for marker in ["pricing", "product", "features", "download", "buy now", "vendor"]):
        return "product/vendor page"
    return "unclear source type"


def build_repeated_patterns(sources: list[dict]) -> list[str]:
    patterns = []
    for _theme, matcher, message in RESEARCH_THEMES:
        matching_sources = 0
        for source in sources:
            if matcher.search(" ".join([str(source.get("title") or ""), str(source.get("snippet") or "")])):
                matching_sources += 1
        if matching_sources >= 2:
            patterns.append(message)
    return patterns


def build_source_types(sources: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for source in sources:
        source_type = classify_source(source)
        counts[source_type] = counts.get(source_type, 0) + 1

    ordered_types = [
        "official docs/help",
        "community discussion",
        "video/tutorial",
        "social/forum",
        "product/vendor page",
        "unclear source type",
    ]
    return [
        f"{source_type}: {counts[source_type]} source{'s' if counts[source_type] != 1 else ''}"
        for source_type in ordered_types
        if counts.get(source_type)
    ] or ["No source types identified."]


def build_evidence_quality(sources: list[dict]) -> list[str]:
    if not sources:
        return ["no sources returned; retry with a broader query or different source target"]

    source_types = {classify_source(source) for source in sources}
    quality = []
    if "official docs/help" in source_types:
        quality.append("primary/official source present")
    if "community discussion" in source_types or "social/forum" in source_types:
        quality.append("forum/user report present")
    if "video/tutorial" in source_types:
        quality.append("video/tutorial source present")
    if len(sources) == 1:
        quality.append("single-source claims need verification")
    if not quality:
        quality.append("source mix needs manual verification")
    return quality


def build_weak_signals(sources: list[dict]) -> list[str]:
    source_types = [classify_source(source) for source in sources]
    weak_signals = []
    if source_types.count("social/forum") == 1 or source_types.count("community discussion") == 1:
        weak_signals.append("single social or community source should be treated as weak evidence")
    if source_types.count("video/tutorial") == 1:
        weak_signals.append("single YouTube/tutorial source should not be treated as consensus")
    if "unclear source type" in source_types:
        weak_signals.append("unclear source type needs manual review")
    for source in sources:
        if re.search(r"\b(best|revolutionary|ultimate|game[- ]?changing|buy now|limited time)\b", source_text(source), re.I):
            weak_signals.append("snippet looks promotional and should be verified against neutral sources")
            break
    return weak_signals


def build_suggested_next_queries(
    query: str,
    sources: list[dict],
    *,
    stemlab: bool = False,
    bishop: bool = False,
) -> list[str]:
    if stemlab:
        return [
            f"{query} reddit complaints",
            f"{query} Ableton workflow",
            f"{query} artifacts quality",
            f"{query} comparison Serato RipX Moises",
            f"{query} producer workflow",
        ]
    if bishop:
        return [
            f"{query} official docs",
            f"{query} implementation examples",
            f"{query} risks limitations",
            f"{query} Slack agent pattern",
            f"{query} memory system pattern",
        ]

    source_types = {classify_source(source) for source in sources}
    queries = [
        f"{query} official documentation",
        f"{query} limitations reliability",
        f"{query} independent comparison",
    ]
    if "community discussion" not in source_types and "social/forum" not in source_types:
        queries.append(f"{query} user reviews complaints")
    if "video/tutorial" not in source_types:
        queries.append(f"{query} tutorial workflow")
    return queries[:5]


def build_research_result(
    query: str,
    sources: list[dict],
    provider: str,
    *,
    stemlab: bool = False,
    bishop: bool = False,
) -> dict:
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
    elif bishop:
        product_implications.insert(
            0,
            "Evaluate whether the evidence suggests a small, safe Bishop improvement worth a separate approved sprint.",
        )

    return {
        "available": True,
        "provider": provider,
        "query": query,
        "research_shape": research_shape(stemlab=stemlab, bishop=bishop),
        "access_limits": RESEARCH_ACCESS_LIMITS,
        "sources": sources,
        "findings": findings,
        "confidence": confidence,
        "repeated_patterns": build_repeated_patterns(sources),
        "evidence_quality": build_evidence_quality(sources),
        "weak_signals": build_weak_signals(sources),
        "source_types": build_source_types(sources),
        "suggested_next_queries": build_suggested_next_queries(query, sources, stemlab=stemlab, bishop=bishop),
        "product_implications": product_implications,
        "open_questions": open_questions,
        "suggested_memory_item": (
            "No memory was saved. Only save after Matt explicitly asks and a specific source supports the finding."
        ),
        "stemlab": stemlab,
        "bishop": bishop,
    }


def run_web_research(query: str, *, stemlab: bool = False, bishop: bool = False, limit: int = 5) -> dict:
    cleaned_query = clean_query(query)
    available, message, provider = validate_research_config()
    if not cleaned_query:
        result = build_unavailable_research_result(cleaned_query, stemlab=stemlab, bishop=bishop)
        result["missing_configuration"] = "No research query was provided"
        return result

    if not available:
        return build_unavailable_research_result(cleaned_query, stemlab=stemlab, bishop=bishop)

    try:
        sources = search_provider(cleaned_query, limit=limit)
    except Exception as exc:
        return {
            "available": False,
            "provider": provider,
            "query": cleaned_query,
            "missing_configuration": f"Research provider request failed: {str(exc)}",
            "next_setup_step": "Check RESEARCH_PROVIDER, RESEARCH_API_KEY, RESEARCH_API_URL, and provider access.",
            "research_shape": research_shape(stemlab=stemlab, bishop=bishop),
            "access_limits": RESEARCH_ACCESS_LIMITS,
            "stemlab": stemlab,
            "bishop": bishop,
        }

    return build_research_result(cleaned_query, sources, provider, stemlab=stemlab, bishop=bishop)
