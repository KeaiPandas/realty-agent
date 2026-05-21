"""微信机器人 SSE 事件流"""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from services.bot import subscribe_bot_events, unsubscribe_bot_events


router = APIRouter()


@router.get("/stream")
async def bot_stream(request: Request):
    async def event_generator():
        q = subscribe_bot_events()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    event_type = event.get("type", "bot.event")
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_bot_events(q)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
