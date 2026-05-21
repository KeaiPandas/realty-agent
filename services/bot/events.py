"""Bot SSE 事件广播"""
import asyncio

from api.event_bus import event_bus

CHANNEL = "bot_events"


def broadcast(event: dict):
    event_bus.publish(CHANNEL, event)


def subscribe() -> asyncio.Queue:
    return event_bus.subscribe(CHANNEL)


def unsubscribe(q: asyncio.Queue):
    event_bus.unsubscribe(CHANNEL, q)
