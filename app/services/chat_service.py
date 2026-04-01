from openai import OpenAI
from app.config import settings
from app.services.memory_service import search_memories

client = OpenAI(api_key=settings.OPENAI_API_KEY)


def generate_memory_context(user_id: str, query: str, limit: int = 8) -> str:
    matches = search_memories(user_id=user_id, query=query, limit=limit)
    if not matches:
        return "No relevant memory found."

    lines = [f"- {m['content']}" for m in matches]
    return "\n".join(lines)


def generate_reply(user_id: str, message: str) -> str:
    if not settings.OPENAI_API_KEY:
        return "I’m missing an OpenAI API key."

    memory_context = generate_memory_context(user_id=user_id, query=message)

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
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )

    return response.output_text.strip()
