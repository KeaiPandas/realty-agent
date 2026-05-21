"""统一事件总线 — SSE 广播基础设施

供 tool_logger（管道日志）和 bot events（机器人事件）共用。
"""
import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def publish(self, channel: str, event: dict[str, Any]):
        for q in self._subscribers.get(channel, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self, channel: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=200)
        self._subscribers[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        subs = self._subscribers.get(channel, [])
        if q in subs:
            subs.remove(q)


# 全局单例
event_bus = EventBus()
