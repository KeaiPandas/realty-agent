"""日志历史 + SSE 实时流"""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from api.tool_logger import get_logs, subscribe, unsubscribe

router = APIRouter()


@router.get("")
async def log_history(limit: int = 100):
    entries = get_logs(limit=limit)
    return {"entries": entries, "total": len(entries)}


@router.get("/stream")
async def log_stream(request: Request):
    queue = subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
