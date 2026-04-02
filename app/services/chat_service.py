import re
from app.services.memory_service import search_memories
from app.services.mode_service import get_mode
from app.services.provider_service import generate_text


def extract_queries(message: str) -> list[str]:
    queries = [message.strip()]

    cleaned = re.sub(r"[^\w\s]", "", message).strip()
    if cleaned and cleaned not in queries:
        queries.append(cleaned)

    words = [w for w in cleaned.split() if len(w) >= 3]
    stop_words = {
        "what", "do", "you", "know", "about", "help", "me", "with",
        "tell", "draft", "write", "for", "and", "the", "that", "this"
    }

    keywords = [w for w in words if w.lower() not in stop_words]
    for word in keywords:
        if word not in queries:
            queries.append(word)

    return queries


def generate_memory_context(user_id: str, message: str, limit: int = 8) -> str:
    seen = set()
    matches = []

    for query in extract_queries(message):
        results = search_memories(user_id=user_id, query=query, limit=limit)
        for item in results:
            if item["id"] not in seen:
                seen.add(item["id"])
                matches.append(item)

    if not matches:
        return "No relevant memory found."

    lines = [f"- {m['content']}" for m in matches[:limit]]
    return "\n".join(lines)


def get_mode_system_prompt(mode: str) -> str:
    prompts = {
        "default": (
            "You are Bishop, a helpful private AI assistant for Matt. "
            "Be practical, clear, concise, warm, and useful. "
            "Use the provided memory when it is relevant, but do not invent facts. "
            "If memory is not relevant, answer normally."
        ),
        "work": (
            "You are Bishop in work mode for Matt. "
            "Be concise, strategic, direct, and professionally useful. "
            "Lead with the answer. Focus on action, decisions, structure, and business value. "
            "Prefer short responses unless more detail is clearly needed. "
            "Avoid unnecessary warmth, filler, and over-explaining. "
            "Use the provided memory when it is relevant, but do not invent facts."
        ),
        "personal": (
            "You are Bishop in personal mode for Matt. "
            "Be warm, supportive, practical, and thoughtful. "
            "Help with life, family, relationships, and personal decisions in a grounded way. "
            "Use the provided memory when it is relevant, but do not invent facts. "
            "If memory is not relevant, answer normally."
        ),
    }
    return prompts.get(mode, prompts["default"])


def generate_reply(user_id: str, message: str) -> str:
    mode = get_mode(user_id)
    memory_context = generate_memory_context(user_id=user_id, message=message)
    system_prompt = get_mode_system_prompt(mode)

    user_prompt = f"""
Current mode:
{mode}

Relevant memory:
{memory_context}

User message:
{message}
""".strip()

    return generate_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
