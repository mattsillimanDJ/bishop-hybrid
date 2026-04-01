import re
from openai import OpenAI
from app.config import settings
from app.services.memory_service import search_memories

client = OpenAI(api_key=settings.OPENAI_API_KEY)


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


def generate_reply(user_id: str, message: str) -> str:
    if not settings.OPENAI_API_KEY:
        return "I’m missing an OpenAI API key."

    memory_context = generate_memory_context(user_id=user_id, message=message)

    system_prompt = (
        "You are Bishop, a helpful private AI assistant for Matt. "
        "Be practical, concise, warm, and useful. "
        "Use the provided memory when it is relevant, but do not invent facts. "
        "If the memory is not relevant, answer normally and say less rather than more."
    )

    user_prompt = f"""
Relevant memory:
{memory_context}

User message:
{message}
""".strip()

    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.output_text.strip()
