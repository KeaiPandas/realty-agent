"""工具调用日志 — 环形缓冲区 + SSE 广播"""
import asyncio
import time
import uuid
from collections import deque

from api.event_bus import event_bus

CHANNEL = "pipeline_logs"
MAX_LOG_ENTRIES = 1000
_log_buffer: deque[dict] = deque(maxlen=MAX_LOG_ENTRIES)


def log_step(step_name: str, run_id: str = "", **extra) -> str:
    """记录管道步骤开始，返回 entry id"""
    entry_id = str(uuid.uuid4())
    entry = {
        "id": entry_id,
        "type": "tool_start",
        "tool": step_name,
        "run_id": run_id,
        "status": "running",
        "start_time": time.time(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        **extra,
    }
    _log_buffer.append(entry)
    event_bus.publish(CHANNEL, entry)
    return entry_id


def log_step_end(entry_id: str, output: str = "", error: str = ""):
    """记录管道步骤结束"""
    for entry in reversed(_log_buffer):
        if entry["id"] == entry_id:
            if error:
                entry["status"] = "error"
                entry["error"] = error[:500]
            else:
                entry["status"] = "success"
                entry["output"] = str(output)[:500]
            entry["duration_ms"] = int((time.time() - entry["start_time"]) * 1000)
            event_type = "tool_error" if error else "tool_end"
            event_bus.publish(CHANNEL, {"type": event_type, **entry})
            return


def log_pipeline_event(event_type: str, **data):
    """记录管道生命周期事件"""
    event = {
        "type": event_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        **data,
    }
    event_bus.publish(CHANNEL, event)


def get_logs(limit: int = 100) -> list[dict]:
    entries = list(_log_buffer)
    return entries[-limit:]


def subscribe() -> asyncio.Queue:
    import asyncio
    return event_bus.subscribe(CHANNEL)


def unsubscribe(q: asyncio.Queue):
    event_bus.unsubscribe(CHANNEL, q)
