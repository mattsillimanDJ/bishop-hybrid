import random
import re
import time
from typing import Optional

from fastapi import APIRouter, Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import settings
from app.services.chat_service import generate_reply, response_contains_commitment
from app.services.conversation_log_service import (
    get_recent_conversations_for_user,
    log_conversation,
)
from app.services.lane_service import get_default_visibility_for_lane, get_lane_from_channel
from app.services.memory_service import (
    add_memory,
    delete_memory_by_query,
    get_memories,
    search_memories,
)
from app.services.mode_service import VALID_MODES, get_mode, set_mode
from app.services.profile_service import (
    get_display_name_for_bishop_user_id,
    resolve_bishop_user_id,
)
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

LANE_QUERY_MESSAGES = {
    "show lane",
    "what lane am i in",
    "what lane are we in",
    "current lane",
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

ALL_TASK_QUERY_MESSAGES = {
    "show all",
    "show all tasks",
}

CLEAR_TASK_MESSAGES = {
    "clear tasks",
    "clear pending",
    "clear pending tasks",
}

CLEAR_DONE_TASK_MESSAGES = {
    "clear done",
    "clear done tasks",
    "clear completed",
    "clear completed tasks",
}

COMPLETE_TASK_PATTERNS = [
    r"^\s*done\s+",
    r"^\s*complete task\s+",
    r"^\s*complete\s+",
    r"^\s*completed\s+",
    r"^\s*mark done\s+",
    r"^\s*mark task done\s+",
    r"^\s*finished\s+",
    r"^\s*finish\s+",
    r"^\s*i finished\s+",
    r"^\s*i completed\s+",
    r"^\s*i did\s+",
    r"^\s*wrapped\s+",
    r"^\s*wrapped up\s+",
    r"^\s*that's done\s+",
    r"^\s*thats done\s+",
]

REMOVE_DONE_TASK_PATTERNS = [
    r"^\s*remove done task\s+",
    r"^\s*remove completed task\s+",
    r"^\s*delete done task\s+",
    r"^\s*delete completed task\s+",
    r"^\s*drop done task\s+",
    r"^\s*drop completed task\s+",
]

REMOVE_TASK_PATTERNS = [
    r"^\s*remove task\s+",
    r"^\s*delete task\s+",
    r"^\s*drop task\s+",
    r"^\s*forget task\s+",
    r"^\s*remove\s+",
    r"^\s*delete\s+",
    r"^\s*drop\s+",
]

REMEMBER_PATTERNS = [
    r"^\s*can you remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*please remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember(?:\s*[:,-]\s*|\s+)",
]

REMEMBER_SHARED_PATTERNS = [
    r"^\s*remember shared that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember shared this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember shared(?:\s*[:,-]\s*|\s+)",
]

REMEMBER_PRIVATE_PATTERNS = [
    r"^\s*remember private that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember private this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember private(?:\s*[:,-]\s*|\s+)",
]

RECALL_PATTERNS = [
    r"^\s*recall(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you remember about(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you remember of(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you know about(?:\s*[:,-]\s*|\s+)",
]

FORGET_MEMORY_PATTERNS = [
    r"^\s*please forget this(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget this(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget that(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget(?:\s*[:,-]\s*|\s+)",
    r"^\s*stop remembering(?:\s*[:,-]\s*|\s+)",
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


def resolve_slack_channel_name(channel_id: str) -> Optional[str]:
    if not settings.SLACK_BOT_TOKEN:
        return None

    try:
        response = slack_client.conversations_info(channel=channel_id)
        channel = response.get("channel", {})
        return channel.get("name")
    except SlackApiError as e:
        print(f"Slack channel lookup error: {e.response['error']}")
        return None
    except Exception as e:
        print(f"Slack channel lookup unexpected error: {str(e)}")
        return None


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


def should_send_working_message(user_text: str) -> bool:
    normalized = normalize_message_for_dedupe(user_text)
    if not normalized:
        return False

    if normalized in SHORT_FOLLOWUP_MESSAGES:
        return False

    if len(normalized) < 25:
        return False

    return True


def help_text() -> str:
    return (
        "Here are the commands I understand:\n"
        "* remember ...\n"
        "* remember that ...\n"
        "* remember this ...\n"
        "* can you remember this ...\n"
        "* remember shared ...\n"
        "* remember shared that ...\n"
        "* remember private ...\n"
        "* remember private that ...\n"
        "* recall ...\n"
        "* what do you remember\n"
        "* what do you remember about ...\n"
        "* forget ...\n"
        "* forget that ...\n"
        "* forget this ...\n"
        "* please forget this ...\n"
        "* stop remembering ...\n"
        "* show memory\n"
        "* show all memory\n"
        "* what do you remember in full\n"
        "* show recent conversations\n"
        "* show last 5 conversations\n"
        "* show lane\n"
        "* what lane am i in\n"
        "* show tasks\n"
        "* show pending\n"
        "* show done\n"
        "* show completed\n"
        "* show all\n"
        "* show all tasks\n"
        "* clear tasks\n"
        "* clear done\n"
        "* clear completed\n"
        "* add task ...\n"
        "* save task ...\n"
        "* remind me ...\n"
        "* done ...\n"
        "* complete task ...\n"
        "* finished ...\n"
        "* i finished ...\n"
        "* that's done ...\n"
        "* delete ...\n"
        "* remove task ...\n"
        "* delete task ...\n"
        "* drop task ...\n"
        "* remove done task ...\n"
        "* remove completed task ...\n"
        "* mode default\n"
        "* mode work\n"
        "* mode personal\n"
        "* mode website\n"
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


def format_all_tasks_for_slack(pending_items: list[dict], done_items: list[dict]) -> str:
    if not pending_items and not done_items:
        return "No tasks right now."

    sections = []

    sections.append(
        format_tasks_for_slack(
            pending_items,
            title="Pending tasks:",
            empty_text="No pending tasks right now.",
        )
    )
    sections.append("")
    sections.append(
        format_tasks_for_slack(
            done_items,
            title="Completed tasks:",
            empty_text="No completed tasks right now.",
        )
    )

    return "\n".join(sections)


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


def build_lane_text(channel_id: str, lane: str, default_visibility: str) -> str:
    return (
        f"Current lane: {lane}\n"
        f"Channel ID: {channel_id}\n"
        f"Default visibility: {default_visibility}"
    )


def get_tasks_for_lane(user_id: str, lane: str, status: str, limit: int = 10):
    try:
        return get_tasks(user_id=user_id, lane=lane, status=status, limit=limit)
    except TypeError:
        return get_tasks(user_id=user_id, status=status, limit=limit)


def clear_tasks_for_lane(user_id: str, lane: str, status: str):
    try:
        return clear_tasks(user_id=user_id, lane=lane, status=status)
    except TypeError:
        return clear_tasks(user_id=user_id, status=status)


def mark_task_done_for_lane(user_id: str, lane: str, task_text: str):
    try:
        return mark_task_done(user_id=user_id, lane=lane, task_text=task_text)
    except TypeError:
        return mark_task_done(user_id=user_id, task_text=task_text)


def remove_task_for_lane(user_id: str, lane: str, task_text: str, status: str):
    try:
        return remove_task(user_id=user_id, lane=lane, task_text=task_text, status=status)
    except TypeError:
        return remove_task(user_id=user_id, task_text=task_text, status=status)


def add_task_for_lane(
    *,
    user_id: str,
    lane: str,
    channel_id: str,
    session_id: str,
    source_message: str,
    task_text: str,
    assistant_commitment: str,
    status: str = "pending",
):
    try:
        return add_task(
            user_id=user_id,
            lane=lane,
            channel_id=channel_id,
            session_id=session_id,
            source_message=source_message,
            task_text=task_text,
            assistant_commitment=assistant_commitment,
            status=status,
        )
    except TypeError:
        return add_task(
            user_id=user_id,
            channel_id=channel_id,
            session_id=session_id,
            source_message=source_message,
            task_text=task_text,
            assistant_commitment=assistant_commitment,
            status=status,
        )


def build_status_text(user_id: str, lane: str) -> tuple[str, str]:
    current_mode = get_mode(user_id)
    resolution = get_provider_resolution()
    effective_provider = resolution["effective_provider"]
    active_model = get_provider_model(effective_provider) or "not set"
    pending_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)

    openai_ok, openai_message = validate_provider_config("openai")
    claude_ok, claude_message = validate_provider_config("claude")

    response_text = (
        "*Bishop Status*\n\n"
        f"*Mode:* {current_mode}\n"
        f"*Lane:* {lane}\n"
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


def extract_by_patterns(message: str, patterns: list[str]) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()
    for pattern in patterns:
        match = re.match(pattern, lowered)
        if match:
            extracted = original[match.end():].strip()
            extracted = re.sub(r"\s+", " ", extracted).strip()
            return extracted or None

    return None


def extract_task_text_for_completion(message: str) -> str | None:
    return extract_by_patterns(message, COMPLETE_TASK_PATTERNS)


def extract_task_text_for_done_removal(message: str) -> str | None:
    return extract_by_patterns(message, REMOVE_DONE_TASK_PATTERNS)


def extract_task_text_for_removal(message: str) -> str | None:
    return extract_by_patterns(message, REMOVE_TASK_PATTERNS)


def extract_memory_text_for_remember(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_PATTERNS)


def extract_memory_text_for_remember_shared(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_SHARED_PATTERNS)


def extract_memory_text_for_remember_private(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_PRIVATE_PATTERNS)


def extract_memory_text_for_recall(message: str) -> str | None:
    return extract_by_patterns(message, RECALL_PATTERNS)


def extract_memory_text_for_forget(message: str) -> str | None:
    return extract_by_patterns(message, FORGET_MEMORY_PATTERNS)


def resolve_memory_visibility(user_text: str, lane_default_visibility: str) -> tuple[str, str | None, bool]:
    remembered_text = extract_memory_text_for_remember_shared(user_text)
    if remembered_text:
        return "shared", remembered_text, True

    remembered_text = extract_memory_text_for_remember_private(user_text)
    if remembered_text:
        return "private", remembered_text, True

    remembered_text = extract_memory_text_for_remember(user_text)
    if remembered_text:
        return lane_default_visibility, remembered_text, False

    return lane_default_visibility, None, False


def get_result_status(result: object) -> str | None:
    if not isinstance(result, dict):
        return None

    status = result.get("status")
    if not isinstance(status, str):
        return None

    normalized_status = status.strip().lower()
    return normalized_status or None


def get_result_flag(result: object, flag_name: str) -> bool:
    if not isinstance(result, dict):
        return False

    if bool(result.get(flag_name)):
        return True

    status = get_result_status(result)

    if flag_name == "updated":
        return status == "updated"

    if flag_name == "deleted":
        return status == "deleted"

    return False


def get_result_task_text(result: object, fallback_text: str) -> str:
    if isinstance(result, dict):
        nested_task = result.get("task")
        if isinstance(nested_task, dict):
            nested_text = (nested_task.get("task_text") or "").strip()
            if nested_text:
                return nested_text

        top_level_text = (result.get("task_text") or "").strip()
        if top_level_text:
            return top_level_text

    return fallback_text


def get_deleted_count(result: object) -> int:
    if not isinstance(result, dict):
        return 0

    deleted_value = result.get("deleted", 0)
    if isinstance(deleted_value, bool):
        return int(deleted_value)

    try:
        return int(deleted_value)
    except (TypeError, ValueError):
        return 0


def clean_string(value: object, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


LOW_SIGNAL_MEMORY_CATEGORIES = frozenset({"profile", "preference"})

OPERATIONAL_SIGNAL_KEYWORDS = (
    "bishop",
    "building",
    "working",
    "workflow",
    "terminal",
    "full-file",
    "pytest",
    "commit",
    "push",
    "actionable",
    "project",
    "priority",
)

_OPERATIONAL_SIGNAL_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(keyword) for keyword in OPERATIONAL_SIGNAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def has_operational_signal(content: str) -> bool:
    if not content:
        return False
    return bool(_OPERATIONAL_SIGNAL_PATTERN.search(content))

BOILERPLATE_MEMORY_CONTENTS = frozenset(
    {
        "user's name is matt.",
        "matt is an advertising executive and dj.",
        "bishop is a private ai workspace for work, dj/music, family, carmen, and general life.",
        "matt prefers clear, practical, strategic help.",
        "matt wants bishop to feel like a personal ai operating system, not a generic chatbot.",
    }
)

_SUPPRESSION_WHITESPACE_PATTERN = re.compile(r"\s+")
_SUPPRESSION_SPACE_BEFORE_COMMA_PATTERN = re.compile(r"\s+,")
_SUPPRESSION_TRAILING_PUNCT_PATTERN = re.compile(r"[.!?]+$")


def normalize_memory_content_for_suppression(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = (
        value.replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", ",")
        .replace("–", ",")
    )
    normalized = _SUPPRESSION_WHITESPACE_PATTERN.sub(" ", normalized).strip()
    normalized = _SUPPRESSION_SPACE_BEFORE_COMMA_PATTERN.sub(",", normalized)
    normalized = _SUPPRESSION_TRAILING_PUNCT_PATTERN.sub("", normalized)
    return normalized.casefold()


_NORMALIZED_BOILERPLATE_MEMORY_CONTENTS = frozenset(
    normalize_memory_content_for_suppression(entry) for entry in BOILERPLATE_MEMORY_CONTENTS
)


def suppress_boilerplate_memory_items(items: list[dict]) -> list[dict]:
    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = normalize_memory_content_for_suppression(item.get("content"))
        if normalized in _NORMALIZED_BOILERPLATE_MEMORY_CONTENTS:
            continue
        filtered.append(item)
    return filtered


def normalize_memory_item(item: object, fallback_lane: str) -> dict | None:
    if not isinstance(item, dict):
        return None

    content = clean_string(item.get("content"))
    if not content:
        return None

    lane = clean_string(item.get("lane"), fallback_lane)
    visibility = clean_string(item.get("visibility"), "unknown")
    category = clean_string(item.get("category"))

    owner_user_id = clean_string(item.get("owner_user_id"))
    if not owner_user_id:
        owner_user_id = clean_string(item.get("user_id"), "unknown")

    owner_display_name = clean_string(get_display_name_for_bishop_user_id(owner_user_id))
    if not owner_display_name and owner_user_id != "unknown":
        owner_display_name = owner_user_id

    return {
        "lane": lane,
        "visibility": visibility,
        "category": category,
        "content": content,
        "owner_user_id": owner_user_id,
        "owner_display_name": owner_display_name,
    }


def dedupe_memory_items(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (
            clean_string(item.get("lane"), "unknown"),
            clean_string(item.get("visibility"), "unknown"),
            clean_string(item.get("owner_user_id"), "unknown"),
            clean_string(item.get("content")).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def rerank_memory_items(items: list[dict]) -> list[dict]:
    def is_low_signal(item: dict) -> int:
        category = clean_string(item.get("category")).casefold()
        return 1 if category in LOW_SIGNAL_MEMORY_CATEGORIES else 0

    return sorted(items, key=is_low_signal)


def get_safe_memory_items(result: object, fallback_lane: str) -> list[dict]:
    if not isinstance(result, (list, tuple)):
        return []

    normalized_items = []
    for item in result:
        normalized_item = normalize_memory_item(item, fallback_lane)
        if normalized_item is not None:
            normalized_items.append(normalized_item)

    return normalized_items


def format_memory_line(item: dict) -> str:
    if not isinstance(item, dict):
        return "* unknown in unknown:"

    owner_display_name = clean_string(item.get("owner_display_name"))
    visibility = clean_string(item.get("visibility"), "unknown")
    lane = clean_string(item.get("lane"), "unknown")
    content = clean_string(item.get("content"))

    if owner_display_name:
        return f"* {owner_display_name} {visibility} in {lane}: {content}"

    return f"* {visibility} in {lane}: {content}"


def format_memory_lines(items: list[dict]) -> list[str]:
    return [format_memory_line(item) for item in items]


def partition_memory_items_by_profile(items: list[dict]) -> tuple[list[dict], list[dict]]:
    working: list[dict] = []
    background: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        category = clean_string(item.get("category")).casefold()
        if category not in LOW_SIGNAL_MEMORY_CATEGORIES:
            working.append(item)
        elif has_operational_signal(clean_string(item.get("content"))):
            working.append(item)
        else:
            background.append(item)
    return working, background


def was_memory_deleted(result: object) -> bool:
    return get_deleted_count(result) > 0


def get_deleted_memory_lane(result: object, fallback_lane: str) -> str:
    if not isinstance(result, dict):
        return fallback_lane
    return clean_string(result.get("lane"), fallback_lane)


def build_lane_memory_response(
    user_id: str, lane: str, include_boilerplate: bool = False
) -> str:
    raw_memories = get_memories(user_id=user_id, lane=lane, limit=20)
    memories = get_safe_memory_items(raw_memories, lane)
    memories = rerank_memory_items(dedupe_memory_items(memories))
    if not include_boilerplate:
        suppressed = suppress_boilerplate_memory_items(memories)
        if suppressed or not memories:
            memories = suppressed
    if not memories:
        return f"I do not have any saved memory yet in the {lane} lane."

    header = f"Here is what I remember in the {lane} lane:"

    if include_boilerplate:
        return header + "\n" + "\n".join(format_memory_lines(memories))

    working, background = partition_memory_items_by_profile(memories)
    sections: list[str] = [header]
    if working:
        sections.append("Working memory:")
        sections.extend(format_memory_lines(working))
    if background:
        sections.append("Background profile:")
        sections.extend(format_memory_lines(background))
    return "\n".join(sections)


def build_lane_memory_section_response(user_id: str, lane: str, section: str) -> str:
    raw_memories = get_memories(user_id=user_id, lane=lane, limit=20)
    memories = get_safe_memory_items(raw_memories, lane)
    memories = rerank_memory_items(dedupe_memory_items(memories))
    suppressed = suppress_boilerplate_memory_items(memories)
    if suppressed or not memories:
        memories = suppressed

    working, background = partition_memory_items_by_profile(memories)

    if section == "working":
        items = working
        header = f"Working memory in the {lane} lane:"
        empty = f"I do not have any working memory yet in the {lane} lane."
    else:
        items = background
        header = f"Background profile in the {lane} lane:"
        empty = f"I do not have any background profile yet in the {lane} lane."

    if not items:
        return empty

    return header + "\n" + "\n".join(format_memory_lines(items))


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

    slack_user_id = event.get("user")
    user_id = resolve_bishop_user_id(slack_user_id or "")
    channel_id = event.get("channel")
    raw_text = event.get("text", "")
    user_text = strip_app_mention(raw_text)

    if not user_id or not channel_id or not user_text:
        return {"ok": True}

    if is_duplicate_recent_message(user_id=user_id, channel_id=channel_id, user_text=user_text):
        return {"ok": True}

    lane = get_lane_from_channel(channel_id, resolver=resolve_slack_channel_name)
    default_visibility = get_default_visibility_for_lane(lane)

    try:
        lowered = user_text.lower().strip()

        if lowered == "help":
            response_text = help_text()
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        memory_command_key = lowered.rstrip(" \t?!.,;:")

        if memory_command_key in {"what do you remember", "show memory"}:
            response_text = build_lane_memory_response(user_id=user_id, lane=lane)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key in {"show all memory", "what do you remember in full"}:
            response_text = build_lane_memory_response(
                user_id=user_id, lane=lane, include_boilerplate=True
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key == "show working memory":
            response_text = build_lane_memory_section_response(
                user_id=user_id, lane=lane, section="working"
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key == "show background profile":
            response_text = build_lane_memory_section_response(
                user_id=user_id, lane=lane, section="background"
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if lowered in LANE_QUERY_MESSAGES:
            response_text = build_lane_text(
                channel_id=channel_id,
                lane=lane,
                default_visibility=default_visibility,
            )
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        memory_visibility, remembered_text, is_explicit_visibility = resolve_memory_visibility(
            user_text=user_text,
            lane_default_visibility=default_visibility,
        )
        if remembered_text:
            add_memory(
                user_id=user_id,
                category="note",
                content=remembered_text,
                lane=lane,
                visibility=memory_visibility,
            )
            if is_explicit_visibility:
                response_text = (
                    f"Got it. I'll remember this as {memory_visibility} in the {lane} lane: "
                    f"{remembered_text}"
                )
            else:
                response_text = f"Got it. I'll remember this in the {lane} lane: {remembered_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        recalled_query = extract_memory_text_for_recall(user_text)
        if recalled_query:
            raw_results = search_memories(
                user_id=user_id,
                query=recalled_query,
                lane=lane,
                limit=5,
            )
            results = get_safe_memory_items(raw_results, lane)
            if results:
                response_text = "Here is what I found:\n" + "\n".join(format_memory_lines(results))
            else:
                response_text = f"I could not find anything matching that in the {lane} lane."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        forgotten_query = extract_memory_text_for_forget(user_text)
        if forgotten_query:
            deleted = delete_memory_by_query(
                user_id=user_id,
                query=forgotten_query,
                lane=lane,
            )
            if was_memory_deleted(deleted):
                deleted_lane = get_deleted_memory_lane(deleted, lane)
                response_text = f"Forgot memory in the {deleted_lane} lane matching: {forgotten_query}"
            else:
                response_text = f"I could not find anything to forget for: {forgotten_query} in the {lane} lane."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
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
            tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Pending tasks:",
                empty_text="No pending tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in DONE_TASK_QUERY_MESSAGES:
            tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="done", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Completed tasks:",
                empty_text="No completed tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in ALL_TASK_QUERY_MESSAGES:
            pending_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)
            done_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="done", limit=10)
            response_text = format_all_tasks_for_slack(pending_tasks, done_tasks)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in CLEAR_TASK_MESSAGES:
            result = clear_tasks_for_lane(user_id=user_id, lane=lane, status="pending")
            deleted_count = get_deleted_count(result)
            response_text = f"Cleared {deleted_count} pending task(s)."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in CLEAR_DONE_TASK_MESSAGES:
            result = clear_tasks_for_lane(user_id=user_id, lane=lane, status="done")
            deleted_count = get_deleted_count(result)
            response_text = f"Cleared {deleted_count} completed task(s)."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        completed_task_text = extract_task_text_for_completion(user_text)
        if completed_task_text:
            result = mark_task_done_for_lane(user_id=user_id, lane=lane, task_text=completed_task_text)
            if get_result_flag(result, "updated"):
                result_task_text = get_result_task_text(result, completed_task_text)
                response_text = f"Marked done: {result_task_text}"
            else:
                response_text = f"I could not find a pending task matching: {completed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        removed_done_task_text = extract_task_text_for_done_removal(user_text)
        if removed_done_task_text:
            result = remove_task_for_lane(
                user_id=user_id,
                lane=lane,
                task_text=removed_done_task_text,
                status="done",
            )
            if get_result_flag(result, "deleted"):
                result_task_text = get_result_task_text(result, removed_done_task_text)
                response_text = f"Removed completed task: {result_task_text}"
            else:
                response_text = f"I could not find a completed task matching: {removed_done_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        removed_task_text = extract_task_text_for_removal(user_text)
        if removed_task_text:
            result = remove_task_for_lane(
                user_id=user_id,
                lane=lane,
                task_text=removed_task_text,
                status="pending",
            )
            if get_result_flag(result, "deleted"):
                result_task_text = get_result_task_text(result, removed_task_text)
                response_text = f"Removed pending task: {result_task_text}"
            else:
                response_text = f"I could not find a pending task matching: {removed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if should_capture_task_from_user_message(user_text):
            task_text = build_task_text_from_user_message(user_text)
            if task_text:
                task_result = add_task_for_lane(
                    user_id=user_id,
                    lane=lane,
                    channel_id=channel_id,
                    session_id=channel_id,
                    source_message=user_text,
                    task_text=task_text,
                    assistant_commitment="Saved as a pending task.",
                    status="pending",
                )
                if isinstance(task_result, dict):
                    result_task_text = task_result.get("task_text", task_text)
                    if task_result.get("deduped"):
                        response_text = f"Already in pending tasks: {result_task_text}"
                    else:
                        response_text = f"Saved to pending tasks: {result_task_text}"
                else:
                    response_text = f"Saved to pending tasks: {task_text}"
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
            response_text, active_model = build_status_text(user_id, lane)

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

        if should_send_working_message(user_text):
            working_messages = [
                "Got it, working through that now.",
                "Working on this now, I’ll make it practical.",
                "Thinking it through and putting structure around it.",
            ]
            post_message(channel_id, random.choice(working_messages))

        try:
            response_text = generate_reply(user_id=user_id, message=expanded_user_text)
            if not response_text or not response_text.strip():
                raise ValueError("Empty response from generate_reply")
        except Exception as e:
            print(f"[Bishop] generate_reply failed: {str(e)}")
            response_text = (
                "I hit an issue while putting that together. "
                "Send it again and I’ll take another pass."
            )

        post_message(channel_id, response_text)

        try:
            effective_provider = get_effective_provider()
            active_model = get_provider_model(effective_provider) or "not set"

            if response_contains_commitment(response_text):
                task_result = add_task_for_lane(
                    user_id=user_id,
                    lane=lane,
                    channel_id=channel_id,
                    session_id=channel_id,
                    source_message=user_text,
                    task_text=user_text,
                    assistant_commitment=response_text,
                    status="pending",
                )
                if isinstance(task_result, dict) and task_result.get("deduped"):
                    result_task_text = task_result.get("task_text", user_text)
                    print(f"Skipped duplicate commitment task for user {user_id} in {lane}: {result_task_text}")

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
        except Exception as e:
            print(f"[Bishop] post-processing failed: {str(e)}")

        return {"ok": True}

    except Exception as e:
        print(f"Slack route unexpected error for user {user_id} in channel {channel_id}: {str(e)}")
        response_text = "Sorry, something went wrong while handling that Slack message."
        post_message(channel_id, response_text)
        return {"ok": True}
