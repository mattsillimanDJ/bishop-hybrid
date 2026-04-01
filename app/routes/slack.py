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

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)


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
    except Exception as e:
        print(f"Unexpected Slack post error: {str(e)}")
        return {"ok": False, "error": str(e)}


def strip_bot_mention(text: str) -> str:
    text = text.strip()
    if text.startswith("<@") and ">" in text:
        text = text.split(">", 1)[1].strip()
    return text


@router.post("/slack/events")
async def slack_events(request: Request):
    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})

    if event.get("type") != "app_mention":
        return {"ok": True}

    channel = event.get("channel")
    raw_text = strip_bot_mention(event.get("text", ""))
    text = raw_text.lower()

    if text.startswith("remember "):
        memory_text = raw_text[9:].strip()
        if memory_text:
            saved = add_memory(user_id="matt", category="slack_memory", content=memory_text)
            result = post_message(channel, f"Got it. I’ll remember: {saved['content']}")
            return {"ok": True, "slack_result": result}

        result = post_message(channel, "I didn’t catch anything to remember.")
        return {"ok": True, "slack_result": result}

    if text.startswith("recall "):
        query = raw_text[7:].strip()
        if not query:
            result = post_message(channel, "Tell me what to recall, for example: `recall Ben`")
            return {"ok": True, "slack_result": result}

        matches = search_memories(user_id="matt", query=query, limit=10)
        if not matches:
            result = post_message(channel, f"I couldn’t find anything about: {query}")
            return {"ok": True, "slack_result": result}

        formatted = "\n".join([f"- {m['content']}" for m in matches])
        result = post_message(channel, f"Here’s what I found about *{query}*:\n{formatted}")
        return {"ok": True, "slack_result": result}

    if text.startswith("forget "):
        query = raw_text[7:].strip()
        if not query:
            result = post_message(channel, "Tell me what to forget, for example: `forget investing`")
            return {"ok": True, "slack_result": result}

        deleted = delete_memory_by_query(user_id="matt", query=query)
        if not deleted["deleted"]:
            result = post_message(channel, f"I couldn’t find a matching memory for: {query}")
            return {"ok": True, "slack_result": result}

        result = post_message(channel, f"Forgot: {deleted['content']}")
        return {"ok": True, "slack_result": result}

    if text == "show memory" or "show memory" in text:
        memories = get_memories(user_id="matt", limit=10)
        if not memories:
            result = post_message(channel, "I don’t have any saved memory yet.")
            return {"ok": True, "slack_result": result}

        formatted = "\n".join([f"- {m['content']}" for m in memories])
        result = post_message(channel, f"Here’s what I remember:\n{formatted}")
        return {"ok": True, "slack_result": result}

    ai_reply = generate_reply(user_id="matt", message=raw_text)
    result = post_message(channel, ai_reply)
    return {"ok": True, "slack_result": result}
