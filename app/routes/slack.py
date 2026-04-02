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
from app.services.conversation_log_service import log_conversation
from app.services.mode_service import get_mode, set_mode, VALID_MODES

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)

processed_event_ids = set()


def post_message(channel: str, text: str):
    if not settings.SLACK_BOT_TOKEN:
        print("Missing SLACK_BOT_TOKEN")
        return {"ok": False, "error": "Missing SLACK_BOT_TOKEN"}

    try:
        response = slack_client.chat_postMessage(channel=channel, text=text)
        return {"ok": response["ok"]}
    except SlackApiError as e:
        error_message = e.response.get("error", "unknown_slack_error")
        print(f"Slack API error: {error_message}")
        return {"ok": False, "error": error_message}


@router.post("/slack/events")
async def slack_events(request: Request):
    retry_num = request.headers.get("x-slack-retry-num")
    retry_reason = request.headers.get("x-slack-retry-reason")

    if retry_num is not None:
        print(f"Ignoring Slack retry #{retry_num}, reason: {retry_reason}")
        return {"ok": True}

    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event_id = payload.get("event_id")
    if event_id:
        if event_id in processed_event_ids:
            print(f"Ignoring duplicate Slack event: {event_id}")
            return {"ok": True}
        processed_event_ids.add(event_id)

    event = payload.get("event", {})

    if not event:
        return {"ok": True}

    if event.get("type") != "app_mention":
        return {"ok": True}

    if event.get("bot_id"):
        return {"ok": True}

    channel_id = event.get("channel")
    user_id = event.get("user")
    raw_text = (event.get("text") or "").strip()

    if not channel_id or not raw_text:
        return {"ok": True}

    parts = raw_text.split(maxsplit=1)
    user_text = parts[1].strip() if len(parts) > 1 else ""

    if not user_text:
        reply_text = "Say something after mentioning me."
        post_message(channel_id, reply_text)

        log_conversation(
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            session_id=channel_id,
            user_message=raw_text,
            assistant_response=reply_text,
            memory_used=False,
            mode="default",
            provider="system",
            model=None,
        )
        return {"ok": True}

    lower_text = user_text.lower()

    try:
        current_mode = get_mode(user_id)

        if lower_text == "help":
            reply_text = (
                "Here’s what I can do:\n"
                "- remember [something]\n"
                "- recall [topic]\n"
                "- forget [topic]\n"
                "- show memory\n"
                "- mode default\n"
                "- mode work\n"
                "- mode personal\n"
                "- show mode\n"
                "- or just ask me a normal question"
            )
            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="help_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text.startswith("remember "):
            memory_text = user_text[9:].strip()

            if not memory_text:
                reply_text = "Tell me what to remember."
            else:
                result = add_memory(user_id=user_id, content=memory_text)
                reply_text = str(result)

            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="memory_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text == "show memory":
            memories = get_memories(user_id=user_id)

            if not memories:
                reply_text = "I do not have any memories saved yet."
            else:
                lines = []
                for memory in memories[:20]:
                    if isinstance(memory, dict):
                        value = (
                            memory.get("content")
                            or memory.get("memory")
                            or memory.get("text")
                            or str(memory)
                        )
                    else:
                        value = str(memory)
                    lines.append(f"- {value}")
                reply_text = "Here’s what I remember:\n" + "\n".join(lines)

            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="memory_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text == "show mode":
            reply_text = f"Current mode: {current_mode}"
            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="mode_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text.startswith("mode "):
            requested_mode = lower_text.replace("mode ", "", 1).strip()

            if requested_mode not in VALID_MODES:
                reply_text = "Invalid mode. Use: default, work, or personal."
            else:
                set_mode(user_id, requested_mode)
                reply_text = f"Mode set to {requested_mode}."

            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="mode_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text.startswith("recall "):
            query = user_text[7:].strip()

            if not query:
                reply_text = "Tell me what you want me to recall."
            else:
                matches = search_memories(user_id=user_id, query=query, limit=10)
                if not matches:
                    reply_text = f"I couldn’t find anything about '{query}'."
                else:
                    lines = []
                    for match in matches[:10]:
                        if isinstance(match, dict):
                            value = (
                                match.get("content")
                                or match.get("memory")
                                or match.get("text")
                                or str(match)
                            )
                        else:
                            value = str(match)
                        lines.append(f"- {value}")
                    reply_text = f"Here’s what I found about '{query}':\n" + "\n".join(lines)

            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=True,
                mode="memory_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        if lower_text.startswith("forget "):
            query = user_text[7:].strip()

            if not query:
                reply_text = "Tell me what you want me to forget."
            else:
                result = delete_memory_by_query(user_id=user_id, query=query)
                reply_text = str(result)

            post_message(channel_id, reply_text)

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=reply_text,
                memory_used=False,
                mode="memory_command",
                provider="system",
                model=None,
            )
            return {"ok": True}

        reply_text = generate_reply(user_id=user_id, message=user_text)
        post_message(channel_id, reply_text)

        log_conversation(
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            session_id=channel_id,
            user_message=user_text,
            assistant_response=reply_text,
            memory_used=True,
            mode=current_mode,
            provider="openai",
            model=settings.OPENAI_MODEL,
        )

        return {"ok": True}

    except Exception as e:
        error_text = f"Something went wrong: {str(e)}"
        print(error_text)
        post_message(channel_id, error_text)

        log_conversation(
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            session_id=channel_id,
            user_message=user_text,
            assistant_response=error_text,
            memory_used=False,
            mode="error",
            provider="system",
            model=None,
        )

        return {"ok": True}
