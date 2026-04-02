import re
import time

from fastapi import APIRouter, Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import settings
from app.services.memory_service import (
    add_memory,
    get_memories,
    search_memories,
    delete_memory_by_query,
)
from app.services.chat_service import generate_reply
from app.services.conversation_log_service import (
    log_conversation,
    get_recent_conversations_for_user,
)
from app.services.mode_service import get_mode, set_mode, VALID_MODES
from app.services.provider_service import (
    get_provider_model,
    validate_provider_config,
)
from app.services.provider_state_service import (
    get_provider_override,
    get_effective_provider,
    set_provider_override,
    clear_provider_override,
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
        "• remember ...\n"
        "• recall ...\n"
        "• forget ...\n"
        "• show memory\n"
        "• show recent conversations\n"
        "• show last 5 conversations\n"
        "• mode default\n"
        "• mode work\n"
        "• mode personal\n"
        "• show mode\n"
        "• show provider\n"
        "• status\n"
        "• provider openai\n"
        "• provider claude\n"
        "• provider default\n"
        "• help\n\n"
        "Or just mention me normally and I’ll reply."
    )


def format_recent_conversations_for_slack(items: list[dict]) -> str:
    if not items:
        return "I don’t have any recent conversations for you yet."

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
            f"• {timestamp}\n"
            f"  You: {user_message}\n"
            f"  Bishop: {assistant_response}"
        )

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

        if lowered.startswith("remember "):
            memory_text = user_text[9:].strip()
            if not memory_text:
                response_text = "Please tell me what to remember."
            else:
                add_memory(user_id=user_id, content=memory_text)
                response_text = f"Got it. I’ll remember: {memory_text}"

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered.startswith("recall "):
            query = user_text[7:].strip()
            if not query:
                response_text = "Please tell me what you want me to recall."
            else:
                results = search_memories(user_id=user_id, query=query, limit=5)
                if results:
                    lines = [f"• {item['content']}" for item in results]
                    response_text = "Here’s what I found:\n" + "\n".join(lines)
                else:
                    response_text = "I couldn’t find anything matching that."

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
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered.startswith("forget "):
            query = user_text[7:].strip()
            if not query:
                response_text = "Please tell me what you want me to forget."
            else:
                deleted = delete_memory_by_query(user_id=user_id, query=query)

                if isinstance(deleted, int):
                    if deleted > 0:
                        response_text = f"Forgot {deleted} memory item(s) matching: {query}"
                    else:
                        response_text = f"I couldn’t find anything to forget for: {query}"
                elif deleted:
                    response_text = f"Forgot memory matching: {query}"
                else:
                    response_text = f"I couldn’t find anything to forget for: {query}"

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered == "show memory":
            memories = get_memories(user_id=user_id, limit=20)
            if memories:
                lines = [f"• {item['content']}" for item in memories]
                response_text = "Here’s what I remember:\n" + "\n".join(lines)
            else:
                response_text = "I don’t have any saved memory yet."

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
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif get_requested_conversation_limit(lowered) is not None:
            limit = get_requested_conversation_limit(lowered) or 5
            items = get_recent_conversations_for_user(
                user_id=user_id,
                limit=limit,
                platform="slack",
                exclude_utility_commands=True,
                fetch_limit=50,
            )
            response_text = format_recent_conversations_for_slack(items)

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered.startswith("mode "):
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

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered == "show mode":
            current_mode = get_mode(user_id)
            response_text = f"Current mode: {current_mode}"

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=current_mode,
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered in {"status", "show config"}:
            current_mode = get_mode(user_id)
            provider_override = get_provider_override()
            effective_provider = get_effective_provider()
            default_provider = settings.LLM_PROVIDER

            openai_ok, openai_message = validate_provider_config("openai")
            claude_ok, claude_message = validate_provider_config("claude")

            response_text = (
                "*Bishop Status*\n\n"
                f"*Mode:* {current_mode}\n"
                f"*Effective provider:* {effective_provider}\n"
                f"*Provider override:* {provider_override or 'none'}\n"
                f"*Railway default provider:* {default_provider}\n\n"
                f"*OpenAI model:* {get_provider_model('openai') or 'not set'}\n"
                f"*Claude model:* {get_provider_model('claude') or 'not set'}\n\n"
                f"*OpenAI config:* {'ok' if openai_ok else openai_message}\n"
                f"*Claude config:* {'ok' if claude_ok else claude_message}"
            )

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=current_mode,
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered == "show provider":
            provider_override = get_provider_override()
            effective_provider = get_effective_provider()
            default_provider = settings.LLM_PROVIDER

            response_text = (
                f"Effective provider: {effective_provider}\n"
                f"Override: {provider_override or 'none'}\n"
                f"Railway default: {default_provider}"
            )

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered.startswith("provider "):
            requested_provider = lowered.replace("provider ", "", 1).strip()

            if requested_provider == "default":
                clear_provider_override()
                response_text = "Provider override cleared. Falling back to Railway default."

            elif requested_provider in {"openai", "claude"}:
                is_valid, validation_message = validate_provider_config(requested_provider)

                if not is_valid:
                    response_text = (
                        f"Could not switch provider to {requested_provider}. "
                        f"{validation_message}"
                    )
                else:
                    set_provider_override(requested_provider)
                    response_text = f"Provider override set to {requested_provider}."

            else:
                response_text = (
                    "Unknown provider. Use: provider openai, provider claude, or provider default."
                )

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        elif lowered == "help":
            response_text = help_text()

            post_message(channel_id, response_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=False,
                mode=get_mode(user_id),
                provider="system",
                model=None,
            )
            return {"ok": True}

        else:
            effective_message = expand_short_followup_message(user_id=user_id, user_text=user_text)
            response_text = generate_reply(user_id=user_id, message=effective_message)
            effective_provider = get_effective_provider()
            model_name = get_provider_model(effective_provider)

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
                model=model_name,
            )
            return {"ok": True}

    except Exception as e:
        response_text = f"Something went wrong: {str(e)}"
        print(response_text)
        post_message(channel_id, response_text)

        log_conversation(
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            session_id=channel_id,
            user_message=user_text,
            assistant_response=response_text,
            memory_used=False,
            mode="error",
            provider="system",
            model=None,
        )
        return {"ok": True}
