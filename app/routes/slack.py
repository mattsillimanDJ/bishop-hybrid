from fastapi import APIRouter, Request
from slack_sdk import WebClient
from app.config import settings
from app.services.memory_service import add_memory, get_memories

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)


def post_message(channel: str, text: str):
    if not settings.SLACK_BOT_TOKEN:
        return {"ok": False, "error": "Missing SLACK_BOT_TOKEN"}

    return slack_client.chat_postMessage(channel=channel, text=text)


@router.post("/slack/events")
async def slack_events(request: Request):
    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})

    if event.get("type") != "app_mention":
        return {"ok": True}

    channel = event.get("channel")
    raw_text = (event.get("text") or "").strip()
    text = raw_text.lower()

    if text.startswith("remember "):
        memory_text = raw_text[9:].strip()
        if memory_text:
            saved = add_memory(user_id="matt", category="slack_memory", content=memory_text)
            post_message(channel, f"Got it. I’ll remember: {saved['content']}")
            return {"ok": True}

        post_message(channel, "I didn’t catch anything to remember.")
        return {"ok": True}

    if "show memory" in text:
        memories = get_memories(user_id="matt", limit=10)
        if not memories:
            post_message(channel, "I don’t have any saved memory yet.")
            return {"ok": True}

        formatted = "\n".join([f"- {m['content']}" for m in memories])
        post_message(channel, f"Here’s what I remember:\n{formatted}")
        return {"ok": True}

    post_message(channel, "Bishop heard you. Try: `remember ...` or `show memory`")
    return {"ok": True}
