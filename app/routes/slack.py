import re
import time

from fastapi import APIRouter, Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import settings
from app.services.chat_service import generate_reply, response_contains_commitment
from app.services.conversation_log_service import (
    get_recent_conversations_for_user,
    log_conversation,
)
from app.services.memory_service import (
    add_memory,
    delete_memory_by_query,
    get_memories,
    search_memories,
)
from app.services.mode_service import VALID_MODES, get_mode, set_mode
from app.services.provider_service import get_provider_model, validate_provider_config
from app.services.provider_state_service import (
    clear_provider_override,
    get_effective_provider,
    get_provider_override,
    get_provider_resolution,
    set_provider_override,
)
from app.services.task_service import (
    add_task,
    build_task_text_from_user_message,
    clear_tasks,
    get_tasks,
    mark_task_done,
    remove_task,
    should_capture_task_from_user_message,
)

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)

processed_event_ids = set()
recent_message_fingerprints: dict[str, float] = {}

MAX_PROCESSED_EVENT_IDS = 1000
MESSAGE_DEDUPE_WINDOW_SECONDS = 8
MESSAGE_DEDUPE_CACHE_LIMIT = 1000

SHORT_FOLLOWUP_MESSAGES = {
    "yes",
    "yes please",
    "yes please!",
    "yep",
    "yeah",
    "sure",
    "sure!",
    "go ahead",
    "please do",
    "do it",
    "more",
    "3 more",
    "three more",
    "ok",
    "okay",
}

MODE_QUERY_MESSAGES = {
    "show mode",
    "what mode are you in",
    "what mode",
    "current mode",
}

TASK_QUERY_MESSAGES = {
    "show tasks",
    "show pending",
    "show pending tasks",
}

DONE_TASK_QUERY_MESSAGES = {
    "show done",
    "show done tasks",
    "show completed",
    "show completed tasks",
}

CLEAR_TASK_MESSAGES = {
    "clear tasks",
    "clear pending",
    "clear pending tasks",
}

COMPLETE_TASK_PATTERNS = [
    r"^\s*done\s+",
    r"^\s*complete task\s+",
    r"^\s*complete\s+",
    r"^\s*mark done\s+",
    r"^\s*mark task done\s+",
]

REMOVE_TASK_PATTERNS = [
    r"^\s*remove task\s+",
    r"^\s*delete task\s+",
    r"^\s*drop task\s+",
]


def post_message(channel: str, text: str):
    if not settings.SLACK_BOT_TOKEN:
        print("Missing SLACK_BOT_TOKEN")
        return {"ok": False, "error": "Missing SLACK_BOT_TOKEN"}

    try:
        response = slack_client.chat_postMessage(channel=channel, text=text)
        return {"ok": True, "ts": response.get("ts")}
    except SlackApiError as e:
        print(f"Slack API error: {e.response['error']}")
        return {"ok": False, "error": e.response["error"]}


def strip_app_mention(text: str) -> str:
    return re.sub(r"<@[^>]+>", "", text).strip()


def normalize_message_for_dedupe(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[!?.。、，,;:]+$", "", normalized)
    return normalized.strip()


def prune_recent_message_fingerprints(now: float):
    expired_keys = [
        key
        for key, timestamp in recent_message_fingerprints.items()
        if now - timestamp > MESSAGE_DEDUPE_WINDOW_SECONDS
    ]
    for key in expired_keys:
        recent_message_fingerprints.pop(key, None)

    if len(recent_message_fingerprints) > MESSAGE_DEDUPE_CACHE_LIMIT:
        oldest_items = sorted(
            recent_message_fingerprints.items(),
            key=lambda item: item[1],
        )[: len(recent_message_fingerprints) - MESSAGE_DEDUPE_CACHE_LIMIT]
        for key, _ in oldest_items:
            recent_message_fingerprints.pop(key, None)


def is_duplicate_recent_message(user_id: str, channel_id: str, user_text: str) -> bool:
    normalized_text = normalize_message_for_dedupe(user_text)
    if not normalized_text:
        return False

    now = time.time()
    prune_recent_message_fingerprints(now)

    fingerprint = f"{user_id}:{channel_id}:{normalized_text}"
    last_seen = recent_message_fingerprints.get(fingerprint)

    if last_seen and now - last_seen <= MESSAGE_DEDUPE_WINDOW_SECONDS:
        print(f"Skipping near-duplicate Slack message: {fingerprint}")
        return True

    recent_message_fingerprints[fingerprint] = now
    return False


def help_text() -> str:
    return (
        "Here are the commands I understand:\n"
        "* remember ...\n"
        "* recall ...\n"
        "* forget ...\n"
        "* show memory\n"
        "* show recent conversations\n"
        "* show last 5 conversations\n"
        "* show tasks\n"
        "* show pending\n"
        "* show done\n"
        "* show completed\n"
        "* clear tasks\n"
        "* add task ...\n"
        "* save task ...\n"
        "* remind me ...\n"
        "* done ...\n"
        "* complete task ...\n"
        "* remove task ...\n"
        "* mode default\n"
        "* mode work\n"
        "* mode personal\n"
        "* show mode\n"
        "* provider\n"
        "* show provider\n"
        "* model\n"
        "* status\n"
        "* provider openai\n"
        "* provider claude\n"
        "* provider default\n"
        "* help\n\n"
        "Or just mention me normally and I'll reply."
    )


def format_recent_conversations_for_slack(items: list[dict]) -> str:
    if not items:
        return "I do not have any recent conversations for you yet."

    lines = ["Here are your recent conversations:"]

    for item in items:
        created_at = item.get("created_at", "")
        timestamp = created_at.replace("T", " ")[:19] if created_at else "unknown time"

        user_message = (item.get("user_message") or "").strip().replace("\n", " ")
        assistant_response = (item.get("assistant_response") or "").strip().replace("\n", " ")

        if len(user_message) > 80:
            user_message = user_message[:77] + "..."
        if len(assistant_response) > 120:
            assistant_response = assistant_response[:117] + "..."

        lines.append(
            f"* {timestamp}\n"
            f"  You: {user_message}\n"
            f"  Bishop: {assistant_response}"
        )

    return "\n".join(lines)


def format_tasks_for_slack(
    items: list[dict],
    *,
    title: str = "Pending tasks:",
    empty_text: str = "No pending tasks right now.",
) -> str:
    if not items:
        return empty_text

    lines = [title]
    for item in items:
        created_at = item.get("created_at", "")
        timestamp = created_at.replace("T", " ")[:19] if created_at else "unknown time"
        task_text = (item.get("task_text") or "").strip()
        assistant_commitment = (item.get("assistant_commitment") or "").strip().replace("\n", " ")

        if len(task_text) > 120:
            task_text = task_text[:117] + "..."
        if len(assistant_commitment) > 120:
            assistant_commitment = assistant_commitment[:117] + "..."

        lines.append(f"* {timestamp}: {task_text}")
        if assistant_commitment:
            lines.append(f"  Commitment: {assistant_commitment}")

    return "\n".join(lines)


def get_requested_conversation_limit(lowered: str) -> int | None:
    if lowered == "show recent conversations":
        return 5

    match = re.fullmatch(r"show last (\d+) conversations", lowered)
    if not match:
        return None

    requested_limit = int(match.group(1))
    if requested_limit < 1:
        return 1
    if requested_limit > 10:
        return 10
    return requested_limit


def is_short_followup_message(user_text: str) -> bool:
    normalized = normalize_message_for_dedupe(user_text)
    return normalized in SHORT_FOLLOWUP_MESSAGES


def assistant_invited_followup(assistant_response: str) -> bool:
    lowered = (assistant_response or "").strip().lower()

    followup_signals = [
        "want 3 more",
        "want three more",
        "want more",
        "want another",
        "want a sharper",
        "want a darker",
        "want one",
        "want me to",
        "i can make them",
        "i can make them:",
        "i can make them more",
    ]

    return any(signal in lowered for signal in followup_signals)


def expand_short_followup_message(user_id: str, user_text: str) -> str:
    if not is_short_followup_message(user_text):
        return user_text

    items = get_recent_conversations_for_user(
        user_id=user_id,
        limit=1,
        platform="slack",
        exclude_utility_commands=True,
        fetch_limit=10,
    )

    if not items:
        return user_text

    previous_item = items[0]
    previous_user_message = (previous_item.get("user_message") or "").strip()
    previous_assistant_response = (previous_item.get("assistant_response") or "").strip()

    if not previous_user_message or not previous_assistant_response:
        return user_text

    if not assistant_invited_followup(previous_assistant_response):
        return user_text

    return (
        "You are continuing a Slack conversation.\n\n"
        f"User's previous message: {previous_user_message}\n"
        f"Your previous reply: {previous_assistant_response}\n"
        f"User's new reply: {user_text}\n\n"
        "Treat the new reply as a short follow-up to the previous exchange. "
        "Directly fulfill the implied request instead of asking what the user wants, "
        "if the previous assistant message already offered a clear next step."
    )


def log_system_response(
    user_id: str,
    channel_id: str,
    user_text: str,
    response_text: str,
    *,
    memory_used: bool = False,
    model: str | None = None,
):
    log_conversation(
        platform="slack",
        user_id=user_id,
        channel_id=channel_id,
        session_id=channel_id,
        user_message=user_text,
        assistant_response=response_text,
        memory_used=memory_used,
        mode=get_mode(user_id),
        provider="system",
        model=model,
    )


def get_active_model_for_effective_provider() -> str:
    effective_provider = get_effective_provider()
    return get_provider_model(effective_provider) or "not set"


def build_provider_summary_text() -> tuple[str, str]:
    resolution = get_provider_resolution()
    effective_provider = resolution["effective_provider"]
    active_model = get_provider_model(effective_provider) or "not set"

    lines = [
        f"Effective provider: {effective_provider}",
        f"Active model: {active_model}",
        f"Override: {resolution['override'] or 'none'}",
        f"Override status: {'OK' if resolution['override_ok'] else resolution['override_message']}",
        f"Default provider: {resolution['default_provider']}",
        f"Default status: {'OK' if resolution['default_ok'] else resolution['default_message']}",
        f"Resolution source: {resolution['effective_from']}",
    ]

    return "\n".join(lines), active_model


def build_status_text(user_id: str) -> tuple[str, str]:
    current_mode = get_mode(user_id)
    resolution = get_provider_resolution()
    effective_provider = resolution["effective_provider"]
    active_model = get_provider_model(effective_provider) or "not set"
    pending_tasks = get_tasks(user_id=user_id, status="pending", limit=10)

    openai_ok, openai_message = validate_provider_config("openai")
    claude_ok, claude_message = validate_provider_config("claude")

    response_text = (
        "*Bishop Status*\n\n"
        f"*Mode:* {current_mode}\n"
        f"*Effective provider:* {effective_provider}\n"
        f"*Active model:* {active_model}\n"
        f"*Provider override:* {resolution['override'] or 'none'}\n"
        f"*Override status:* {'OK' if resolution['override_ok'] else resolution['override_message']}\n"
        f"*Railway default provider:* {resolution['default_provider']}\n"
        f"*Default provider status:* {'OK' if resolution['default_ok'] else resolution['default_message']}\n"
        f"*Resolution source:* {resolution['effective_from']}\n"
        f"*Pending tasks:* {len(pending_tasks)}\n\n"
        "*Provider checks:*\n"
        f"* OpenAI: {'OK' if openai_ok else 'Missing'} , {openai_message}\n"
        f"* Claude: {'OK' if claude_ok else 'Missing'} , {claude_message}"
    )

    return response_text, active_model


def extract_task_text_for_completion(message: str) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()
    for pattern in COMPLETE_TASK_PATTERNS:
        match = re.match(pattern, lowered)
        if match:
            extracted = original[match.end():].strip()
            extracted = re.sub(r"\s+", " ", extracted).strip()
            return extracted or None

    return None


def extract_task_text_for_removal(message: str) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()
    for pattern in REMOVE_TASK_PATTERNS:
        match = re.match(pattern, lowered)
        if match:
            extracted = original[match.end():].strip()
            extracted = re.sub(r"\s+", " ", extracted).strip()
            return extracted or None

    return None


@router.post("/slack/events")
async def slack_events(request: Request):
    body = await request.json()

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    event_id = body.get("event_id")
    if event_id:
        if event_id in processed_event_ids:
            print(f"Skipping duplicate Slack event_id: {event_id}")
            return {"ok": True}
        processed_event_ids.add(event_id)

        if len(processed_event_ids) > MAX_PROCESSED_EVENT_IDS:
            processed_event_ids.pop()

    if request.headers.get("x-slack-retry-num"):
        print("Skipping Slack retry event")
        return {"ok": True}

    if body.get("type") != "event_callback":
        return {"ok": True}

    event = body.get("event", {})

    if event.get("type") != "app_mention":
        return {"ok": True}

    if event.get("bot_id"):
        return {"ok": True}

    user_id = event.get("user")
    channel_id = event.get("channel")
    raw_text = event.get("text", "")
    user_text = strip_app_mention(raw_text)

    if not user_id or not channel_id or not user_text:
        return {"ok": True}

    if is_duplicate_recent_message(user_id=user_id, channel_id=channel_id, user_text=user_text):
        return {"ok": True}

    try:
        lowered = user_text.lower().strip()

        if lowered == "help":
            response_text = help_text()
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered.startswith("remember "):
            memory_text = user_text[9:].strip()
            if not memory_text:
                response_text = "Please tell me what to remember."
            else:
                add_memory(user_id=user_id, category="note", content=memory_text)
                response_text = f"Got it. I'll remember: {memory_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered.startswith("recall "):
            query = user_text[7:].strip()
            if not query:
                response_text = "Please tell me what you want me to recall."
            else:
                results = search_memories(user_id=user_id, query=query, limit=5)
                if results:
                    lines = [f"* {item['content']}" for item in results]
                    response_text = "Here is what I found:\n" + "\n".join(lines)
                else:
                    response_text = "I could not find anything matching that."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if lowered.startswith("forget "):
            query = user_text[7:].strip()
            if not query:
                response_text = "Please tell me what you want me to forget."
            else:
                deleted = delete_memory_by_query(user_id=user_id, query=query)
                if deleted.get("deleted"):
                    response_text = f"Forgot memory matching: {query}"
                else:
                    response_text = f"I could not find anything to forget for: {query}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered == "show memory":
            memories = get_memories(user_id=user_id, limit=20)
            if memories:
                lines = [f"* {item['content']}" for item in memories]
                response_text = "Here is what I remember:\n" + "\n".join(lines)
            else:
                response_text = "I do not have any saved memory yet."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        requested_limit = get_requested_conversation_limit(lowered)
        if requested_limit is not None:
            items = get_recent_conversations_for_user(
                user_id=user_id,
                limit=requested_limit,
                platform="slack",
                exclude_utility_commands=True,
                fetch_limit=50,
            )
            response_text = format_recent_conversations_for_slack(items)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in TASK_QUERY_MESSAGES:
            tasks = get_tasks(user_id=user_id, status="pending", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Pending tasks:",
                empty_text="No pending tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in DONE_TASK_QUERY_MESSAGES:
            tasks = get_tasks(user_id=user_id, status="done", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Completed tasks:",
                empty_text="No completed tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in CLEAR_TASK_MESSAGES:
            result = clear_tasks(user_id=user_id, status="pending")
            response_text = f"Cleared {result['deleted']} pending task(s)."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        completed_task_text = extract_task_text_for_completion(user_text)
        if completed_task_text:
            result = mark_task_done(user_id=user_id, task_text=completed_task_text)
            if result["updated"]:
                response_text = f"Marked done: {result['task']['task_text']}"
            else:
                response_text = f"I could not find a pending task matching: {completed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        removed_task_text = extract_task_text_for_removal(user_text)
        if removed_task_text:
            result = remove_task(user_id=user_id, task_text=removed_task_text, status="pending")
            if result["deleted"]:
                response_text = f"Removed pending task: {result['task']['task_text']}"
            else:
                response_text = f"I could not find a pending task matching: {removed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if should_capture_task_from_user_message(user_text):
            task_text = build_task_text_from_user_message(user_text)
            if task_text:
                task_result = add_task(
                    user_id=user_id,
                    channel_id=channel_id,
                    session_id=channel_id,
                    source_message=user_text,
                    task_text=task_text,
                    assistant_commitment="Saved as a pending task.",
                    status="pending",
                )
                result_task_text = task_result.get("task_text", task_text)
                if task_result.get("deduped"):
                    response_text = f"Already in pending tasks: {result_task_text}"
                else:
                    response_text = f"Saved to pending tasks: {result_task_text}"
            else:
                response_text = "I could not figure out the task text. Please try again."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered.startswith("mode "):
            requested_mode = lowered.replace("mode ", "", 1).strip()

            if requested_mode in VALID_MODES:
                set_mode(user_id, requested_mode)
                response_text = f"Mode set to {requested_mode}."
            else:
                response_text = (
                    "Unknown mode. Available modes: "
                    + ", ".join(sorted(VALID_MODES))
                )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in MODE_QUERY_MESSAGES:
            current_mode = get_mode(user_id)
            response_text = f"Current mode: {current_mode}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in {"provider", "show provider"}:
            response_text, active_model = build_provider_summary_text()

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered == "model":
            active_model = get_active_model_for_effective_provider()
            response_text = f"Active model: {active_model}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered in {"status", "show config"}:
            response_text, active_model = build_status_text(user_id)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered.startswith("provider "):
            requested_provider = lowered.replace("provider ", "", 1).strip()

            if requested_provider == "default":
                clear_provider_override()
                response_text, active_model = build_provider_summary_text()
                response_text = "Provider override cleared.\n" + response_text
            elif requested_provider in {"openai", "claude"}:
                ok, message = validate_provider_config(requested_provider)
                if not ok:
                    response_text, active_model = build_provider_summary_text()
                    response_text = (
                        f"Cannot switch to {requested_provider}: {message}\n"
                        + response_text
                    )
                else:
                    set_provider_override(requested_provider)
                    response_text, active_model = build_provider_summary_text()
                    response_text = (
                        f"Provider override set to {requested_provider}.\n"
                        + response_text
                    )
            else:
                active_model = get_active_model_for_effective_provider()
                response_text = "Unknown provider. Available options: openai, claude, default."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        expanded_user_text = expand_short_followup_message(user_id=user_id, user_text=user_text)
        response_text = generate_reply(user_id=user_id, message=expanded_user_text)

        effective_provider = get_effective_provider()
        active_model = get_provider_model(effective_provider) or "not set"

        if response_contains_commitment(response_text):
            task_result = add_task(
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                source_message=user_text,
                task_text=user_text,
                assistant_commitment=response_text,
                status="pending",
            )
            if task_result.get("deduped"):
                result_task_text = task_result.get("task_text", user_text)
                print(f"Skipped duplicate commitment task for user {user_id}: {result_task_text}")

        post_message(channel_id, response_text)

        log_conversation(
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            session_id=channel_id,
            user_message=user_text,
            assistant_response=response_text,
            memory_used=True,
            mode=get_mode(user_id),
            provider=effective_provider,
            model=active_model,
        )
        return {"ok": True}

    except Exception as e:
        response_text = f"Something went wrong: {str(e)}"
        post_message(channel_id, response_text)
        return {"ok": True}
