import re

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
from app.services.provider_state_service import (
    get_provider_override,
    get_effective_provider,
    set_provider_override,
    clear_provider_override,
)

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)

processed_event_ids = set()


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

        if len(processed_event_ids) > 1000:
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

            openai_key_configured = "yes" if settings.OPENAI_API_KEY else "no"
            anthropic_key_configured = "yes" if settings.ANTHROPIC_API_KEY else "no"
            openai_model = settings.OPENAI_MODEL or "not set"
            anthropic_model = settings.ANTHROPIC_MODEL or "not set"

            response_text = (
                "*Bishop Status*\n\n"
                f"*Mode:* {current_mode}\n"
                f"*Effective provider:* {effective_provider}\n"
                f"*Provider override:* {provider_override or 'none'}\n"
                f"*Railway default provider:* {default_provider}\n\n"
                f"*OpenAI key configured:* {openai_key_configured}\n"
                f"*Anthropic key configured:* {anthropic_key_configured}\n\n"
                f"*OpenAI model:* {openai_model}\n"
                f"*Anthropic model:* {anthropic_model}"
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

            if requested_provider == "openai":
                set_provider_override("openai")
                response_text = "Provider override set to openai."

            elif requested_provider == "claude":
                set_provider_override("claude")
                response_text = "Provider override set to claude."

            elif requested_provider == "default":
                clear_provider_override()
                response_text = "Provider override cleared. Falling back to Railway default."

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
            response_text = generate_reply(user_id=user_id, message=user_text)
            effective_provider = get_effective_provider()

            if effective_provider == "claude":
                model_name = settings.ANTHROPIC_MODEL or None
            else:
                model_name = settings.OPENAI_MODEL or None

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
