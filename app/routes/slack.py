from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/slack/events")
async def slack_events(request: Request):
    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    return {"ok": True}
