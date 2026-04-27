import re
from pathlib import Path

from app.services.memory_service import search_memories
from app.services.mode_service import get_mode
from app.services.provider_service import generate_text
from app.services.provider_state_service import get_effective_provider
from app.services.task_service import get_tasks


MODE_BRAIN_DIR = Path(__file__).resolve().parent.parent / "data" / "mode_brains"


def load_mode_brain(mode: str) -> str:
    try:
        path = MODE_BRAIN_DIR / f"{mode}.md"
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


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
            item_id = item.get("id")
            if item_id not in seen:
                seen.add(item_id)
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
        "cmo": (
            base
            + " "
            + "You are in CMO mode. "
            + "Think like a sharp, practical marketing leader. "
            + "For business, brand, content, campaign, production, social, or growth questions, "
            + "frame your answer through audience, positioning, offer, channel, creative, budget, "
            + "and measurable next action. "
            + "Be direct, strategic, and useful. "
            + "Do not over-format unless the user asks for a plan. "
            + "For simple questions, stay concise."
        ),
        "stemlab": (
            base
            + " "
            + "You are in StemLab mode. "
            + "Think like a music-tech founder, EDM producer, DJ, product strategist, and workflow designer. "
            + "Help with EDM-specific AI music product strategy, usable stem generation, DJ-ready arrangements, "
            + "Ableton workflows, Suno and Udio style prompting, remix workflows, MVP planning, monetization strategy, "
            + "competitive gaps, founder decision-making, and practical next actions. "
            + "Prefer answers organized around core recommendation, why it matters for DJs and producers, "
            + "product implication, technical implication, and next action. "
            + "Be specific, practical, musically literate, and product-minded."
        ),
        "website": (
            base
            + " "
            + "You are Bishop in website mode for Matt. "
            + "Website mode: operate as a strategist, UX planner, copywriter, and builder. "
            + "Always default to this sequence unless Matt clearly asks for something narrower: "
            + "1) clarify audience and goal, "
            + "2) define positioning and messaging, "
            + "3) outline structure, pages, sections, and flow, "
            + "4) write strong, usable copy, "
            + "5) give practical build guidance for Framer, layout, UX, and SEO basics. "
            + "Prefer structured outputs with clear hierarchy. "
            + "When useful, organize answers into Strategy, Structure, Copy, and Build Notes. "
            + "Avoid vague ideas, generic best practices, and safe filler. "
            + "Be specific, usable, opinionated, and build-ready. "
            + "Use Matt's known identity, style, business context, and brand clues from memory whenever relevant. "
            + "If the task is about Matt's DJ brand, event brand, creative company, or personal website, do not answer like it is for a generic person. "
            + "Make the output feel like it was built for Matt specifically. "
            + "Pull forward relevant brand traits, voice, audience, city, aesthetic, offer, and positioning if memory supports them. "
            + "For DJ and event work especially, prioritize feelgood house energy, crowd connection, nightlife credibility, real-world conversion, and a premium but alive tone when relevant. "
            + "Think like a combination of creative director, product strategist, UX planner, brand writer, and web builder."
        ),
    }

    prompt = prompts.get(mode, prompts["default"])

    if mode in {"cmo", "stemlab"}:
        brain = load_mode_brain(mode)
        if brain:
            prompt = prompt + "\n\n" + brain

    return prompt


def get_personalization_guidance(mode: str, memory_context: str) -> str:
    if mode != "website":
        return ""

    if not memory_context or memory_context == "No relevant memory found.":
        return (
            "Website personalization guidance:\n"
            "- Use any clear user-specific clues from the current message.\n"
            "- If identity details are missing, make a reasonable first-pass structure but flag where real brand details should be inserted.\n"
            "- Avoid making the answer feel generic if the request appears personal or brand-specific.\n"
        )

    return (
        "Website personalization guidance:\n"
        "- The memory below likely contains brand, identity, style, audience, or positioning clues.\n"
        "- Use those details actively, not passively.\n"
        "- If relevant memory points to Matt's DJ brand, creative work, events, nightlife style, or business goals, reflect that in the strategy, structure, and copy.\n"
        "- Prefer a distinctive point of view over generic website advice.\n"
    )


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
    personalization_guidance = get_personalization_guidance(mode, memory_context)
    provider = get_effective_provider()

    user_prompt = f"""
Current mode:
{mode}

Pending tasks:
{task_context}

Relevant memory:
{memory_context}

{personalization_guidance}

User message:
{message}
""".strip()

    print(f"[Bishop] Using provider: {provider}")
    print(f"[Bishop] Mode: {mode}")
    print(f"[Bishop] Pending tasks: {task_context}")
    print(f"[Bishop] Memory context: {memory_context}")
    if personalization_guidance:
        print(f"[Bishop] Personalization guidance: {personalization_guidance}")

    return generate_text(
        provider=provider,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    ).strip()
