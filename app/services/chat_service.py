import re

from app.services.memory_service import search_memories
from app.services.mode_service import get_mode
from app.services.provider_service import generate_text
from app.services.provider_state_service import get_effective_provider
from app.services.task_service import get_tasks


COMMITMENT_PATTERNS = [
    r"\bon it\b",
    r"\bi(?:'| a)?ll (?:do|handle|take|cover|proceed with|work on)\b",
    r"\bi(?:'| a)?m going to\b",
    r"\bleave it with me\b",
]


def extract_queries(message: str) -> list[str]:
    queries = [message.strip()]

    cleaned = re.sub(r"[^\w\s]", "", message).strip()
    if cleaned and cleaned not in queries:
        queries.append(cleaned)

    words = [w for w in cleaned.split() if len(w) >= 3]
    stop_words = {
        "what",
        "do",
        "you",
        "know",
        "about",
        "help",
        "me",
        "with",
        "tell",
        "draft",
        "write",
        "for",
        "and",
        "the",
        "that",
        "this",
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


def generate_task_context(user_id: str, limit: int = 5) -> str:
    tasks = get_tasks(user_id=user_id, status="pending", limit=limit)
    if not tasks:
        return "No pending tasks."

    lines = []
    for task in tasks:
        task_text = (task.get("task_text") or "").strip()
        if task_text:
            lines.append(f"- {task_text}")

    if not lines:
        return "No pending tasks."

    return "\n".join(lines)


def get_base_system_prompt() -> str:
    return (
        "You are Bishop, a helpful private AI assistant for Matt. "
        "You are also Matt's private AI operator. "
        "You are not a generic chatbot or customer support assistant. "
        "Your job is to be useful, sharp, grounded, and practical. "
        "Be concise by default. Lead with the answer. "
        "Do not over-explain unless the user clearly needs more detail. "
        "Do not invent facts. Use provided memory only when relevant. "
        "If memory is not relevant, ignore it. "
        "Do not sound corporate, theatrical, or overly eager. "
        "Do not ask broad or unnecessary follow-up questions. "
        "Only ask a follow-up when it is genuinely needed to do the job well. "
        "Avoid filler, fluff, and repetitive framing. "
        "Avoid generic assistant phrases like 'How can I help?', "
        "'Is there anything else I can help with?', or similar. "
        "Do not use em dashes. Use commas or periods instead. "
        "Never imply that you kept working while Matt was away, or that you completed background work, unless the result is already present in this reply or explicitly saved in pending tasks. "
        "If you are not doing the work right now, say that plainly. "
        "Do not say 'On it', 'I'll handle it', or similar unless the work is being completed in this reply or has been explicitly saved as a pending task. "
        "When asked about prior commitments, distinguish clearly between completed work and pending tasks. "
        "Write like a smart, trusted operator helping Matt think clearly and move faster."
    )


def get_mode_system_prompt(mode: str) -> str:
    base = get_base_system_prompt()

    prompts = {
        "default": (
            base
            + " "
            + "Default mode: be practical, clear, concise, and warm without being soft. "
            + "Sound like a highly capable private assistant with good judgment."
        ),
        "work": (
            base
            + " "
            + "You are Bishop in work mode for Matt. "
            + "Work mode: be direct, strategic, and professionally useful. "
            + "Focus on action, decisions, structure, priorities, tradeoffs, and business value. "
            + "Prefer tighter phrasing and executive-ready language."
        ),
        "personal": (
            base
            + " "
            + "You are Bishop in personal mode for Matt. "
            + "Personal mode: be warm, steady, thoughtful, and grounded. "
            + "Help with life, family, relationships, health habits, and personal decisions in a calm, practical way. "
            + "Be supportive without sounding corny or overly emotional."
        ),
    }

    return prompts.get(mode, prompts["default"])


def response_contains_commitment(response_text: str) -> bool:
    lowered = (response_text or "").strip().lower()
    return any(re.search(pattern, lowered) for pattern in COMMITMENT_PATTERNS)


def build_task_text_from_message(message: str) -> str:
    message = (message or "").strip()
    if not message:
        return "Follow up on the previous request."

    normalized = re.sub(r"\s+", " ", message).strip()
    if len(normalized) <= 160:
        return normalized

    return normalized[:157].rstrip() + "..."


def generate_reply(user_id: str, message: str) -> str:
    mode = get_mode(user_id)
    memory_context = generate_memory_context(user_id=user_id, message=message)
    task_context = generate_task_context(user_id=user_id)
    system_prompt = get_mode_system_prompt(mode)
    provider = get_effective_provider()

    user_prompt = f"""
Current mode:
{mode}

Pending tasks:
{task_context}

Relevant memory:
{memory_context}

User message:
{message}
""".strip()

    print(f"[Bishop] Using provider: {provider}")
    print(f"[Bishop] Mode: {mode}")
    print(f"[Bishop] Pending tasks: {task_context}")
    print(f"[Bishop] Memory context: {memory_context}")

    return generate_text(
        provider=provider,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    ).strip()
