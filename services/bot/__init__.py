"""WeChat bot orchestration."""
import asyncio
import time
import uuid
from datetime import datetime

from config import settings

from services.bot.conversation import ConversationManager
from services.bot.events import broadcast, subscribe, unsubscribe
from services.bot.models import BotConversation, BotMessage
from services.bot.monitor import Monitor
from services.bot.responder import generate_reply
from services.bot.sender import PywinautoTransport, SendOutcome, SenderFailure


class WeChatBot:
    def __init__(self, transport=None):
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._start_time: float = 0
        self._reply_tasks: dict[str, asyncio.Task] = {}
        self._conv_mgr = ConversationManager()
        self._transport = transport or PywinautoTransport()
        self._monitor = Monitor(self._conv_mgr, on_customer_msg=self._on_customer_message)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def active_count(self) -> int:
        return self._conv_mgr.active_count

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._running else 0,
            "active_conversations": self._conv_mgr.active_count,
            "pending_replies": sum(
                1
                for conv in self._conv_mgr.conversations.values()
                if conv.pending_reply and conv.pending_reply.reply_status == "pending"
            ),
            "global_settings": self._conv_mgr.get_global_settings(),
            "transport_mode": getattr(self._transport, "transport_mode", "unknown"),
        }

    def get_conversations(self) -> list[dict]:
        result = []
        for conv in self._conv_mgr.conversations.values():
            pending = conv.pending_reply
            effective = self._conv_mgr.get_effective_settings(conv.wxid)
            result.append(
                {
                    "wxid": conv.wxid,
                    "nickname": conv.nickname,
                    "message_count": len(conv.messages),
                    "last_message_time": conv.messages[-1].timestamp if conv.messages else "",
                    "effective_mode": effective["mode"] if effective["enabled"] else "disabled",
                    "mode_source": effective["source"],
                    "pending_reply": {
                        "id": pending.id,
                        "content": pending.content,
                        "reply": pending.reply,
                        "reply_status": pending.reply_status,
                        "reason": pending.reply_status_reason,
                        "timestamp": pending.timestamp,
                    }
                    if pending and pending.reply_status == "pending"
                    else None,
                }
            )
        return result

    def get_messages(self, wxid: str, limit: int = 50) -> list[dict]:
        conv = self._conv_mgr.get(wxid)
        if not conv:
            return []
        return [
            {
                "id": msg.id,
                "wxid": msg.wxid,
                "content": msg.content,
                "is_from_customer": msg.is_from_customer,
                "timestamp": msg.timestamp,
                "reply": msg.reply,
                "reply_status": msg.reply_status,
                "reply_status_reason": msg.reply_status_reason,
            }
            for msg in conv.messages[-limit:]
        ]

    def get_pending(self, wxid: str) -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        pending = conv.pending_reply
        if pending.reply_status != "pending":
            return None
        return {
            "id": pending.id,
            "wxid": pending.wxid,
            "content": pending.content,
            "reply": pending.reply,
            "reply_status": pending.reply_status,
            "reason": pending.reply_status_reason,
            "timestamp": pending.timestamp,
        }

    def update_contact_settings(
        self, wxid: str, mode: str | None = None, enabled: bool | None = None
    ) -> dict:
        result = self._conv_mgr.update_settings(wxid, mode, enabled)
        broadcast({"type": "bot.contact_settings_updated", "settings": result})
        return result

    def get_contact_settings_list(self) -> list[dict]:
        return self._conv_mgr.get_settings_list()

    def update_global_settings(
        self, mode: str | None = None, enabled: bool | None = None
    ) -> dict:
        result = self._conv_mgr.update_global_settings(mode, enabled)
        broadcast({"type": "bot.global_settings_updated", "settings": result})
        return result

    def get_global_settings(self) -> dict:
        return self._conv_mgr.get_global_settings()

    async def start(self):
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._start_time = time.time()
        self._task = asyncio.create_task(self._monitor_loop())
        broadcast({"type": "bot.status_change", "status": "running"})
        print("[Bot] started")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        reply_tasks = [task for task in self._reply_tasks.values() if task and not task.done()]
        for task in reply_tasks:
            task.cancel()
        if reply_tasks:
            await asyncio.gather(*reply_tasks, return_exceptions=True)
        self._reply_tasks.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._loop = None
        broadcast({"type": "bot.status_change", "status": "stopped"})
        print("[Bot] stopped")

    async def _monitor_loop(self):
        try:
            await asyncio.to_thread(self._monitor.initialize)
        except Exception as exc:
            broadcast({"type": "bot.error", "error": str(exc)})
            self._running = False
            return

        while self._running:
            try:
                await asyncio.to_thread(self._monitor.check)
            except Exception as exc:
                broadcast({"type": "bot.error", "error": str(exc)})
            await asyncio.sleep(settings.BOT_POLL_INTERVAL)

    def _on_customer_message(self, conv: BotConversation, msg: BotMessage):
        if all(existing is not msg and existing.id != msg.id for existing in conv.messages):
            conv.messages.append(msg)
        effective = self._conv_mgr.get_effective_settings(conv.wxid)
        if not effective["enabled"]:
            return
        if self._loop and self._loop.is_running():
            current_loop = None
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is self._loop:
                self._schedule_reply_task_on_loop(conv.wxid)
            else:
                self._loop.call_soon_threadsafe(self._schedule_reply_task_on_loop, conv.wxid)
            return
        self._generate_reply_now(conv.wxid)

    def _schedule_reply_task_on_loop(self, wxid: str):
        existing = self._reply_tasks.get(wxid)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(self._debounced_generate_reply(wxid))
        self._reply_tasks[wxid] = task
        conv = self._conv_mgr.get(wxid)
        if conv:
            broadcast(
                {
                    "type": "bot.reply_scheduled",
                    "wxid": conv.wxid,
                    "nickname": conv.nickname,
                    "delay_seconds": settings.BOT_REPLY_DEBOUNCE_SECONDS,
                }
            )

    async def _debounced_generate_reply(self, wxid: str):
        try:
            delay = max(0.0, settings.BOT_REPLY_DEBOUNCE_SECONDS)
            if delay > 0:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        finally:
            current = self._reply_tasks.get(wxid)
            if current is asyncio.current_task():
                self._reply_tasks.pop(wxid, None)

        self._generate_reply_now(wxid)

    def _generate_reply_now(self, wxid: str):
        conv = self._conv_mgr.get(wxid)
        if not conv:
            return
        effective = self._conv_mgr.get_effective_settings(conv.wxid)
        if not effective["enabled"]:
            return
        mode = effective["mode"] or settings.BOT_DEFAULT_MODE
        msg = self._latest_customer_message(conv)
        if not msg:
            return

        reply = generate_reply(conv, self._conv_mgr)
        if not reply:
            return

        msg.reply = reply
        msg.reply_status = "pending"
        msg.reply_status_reason = ""
        conv.pending_reply = msg

        broadcast(
            {
                "type": "bot.reply_generated",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": reply,
                "mode": mode,
                "source": effective["source"],
            }
        )

        if mode == "auto":
            self._dispatch_auto_send(conv, msg)

    @staticmethod
    def _latest_customer_message(conv: BotConversation) -> BotMessage | None:
        for msg in reversed(conv.messages):
            if msg.is_from_customer:
                return msg
        return None

    def _dispatch_auto_send(self, conv: BotConversation, msg: BotMessage):
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._send_pending_reply(conv, msg), self._loop
            )
            future.add_done_callback(self._handle_auto_send_result)
            return

        try:
            asyncio.run(self._send_pending_reply(conv, msg))
        except Exception as exc:
            self._handle_transport_exception(conv, msg, exc)

    def _handle_auto_send_result(self, future):
        try:
            future.result()
        except Exception:
            # The failure was already translated into bot events inside _send_pending_reply.
            return

    def _set_pending_reason(self, conv: BotConversation, msg: BotMessage, reason: str):
        msg.reply_status = "pending"
        msg.reply_status_reason = reason
        conv.pending_reply = msg

    def _handle_transport_exception(self, conv: BotConversation, msg: BotMessage, exc: Exception):
        if isinstance(exc, SenderFailure):
            reason = exc.reason
            detail = exc.detail
        else:
            reason = "send_failed"
            detail = str(exc)
        self._set_pending_reason(conv, msg, reason)
        broadcast(
            {
                "type": "bot.reply_send_failed",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": msg.reply,
                "reason": reason,
                "detail": detail,
            }
        )

    async def _send_pending_reply(self, conv: BotConversation, msg: BotMessage):
        broadcast(
            {
                "type": "bot.reply_send_started",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": msg.reply,
            }
        )

        try:
            outcome = await self._send_message(
                conv.wxid,
                msg.reply,
                nickname=conv.nickname,
                guard_manual_conflict=True,
                search_terms=self._conv_mgr.get_search_terms(conv.wxid),
            )
        except Exception as exc:
            self._handle_transport_exception(conv, msg, exc)
            raise

        if outcome.status != "sent":
            self._set_pending_reason(conv, msg, outcome.reason or "send_failed")
            broadcast(
                {
                    "type": "bot.reply_send_deferred",
                    "wxid": conv.wxid,
                    "nickname": conv.nickname,
                    "reply": msg.reply,
                    "reason": outcome.reason,
                    "detail": outcome.detail,
                }
            )
            return

        msg.reply_status = "sent"
        msg.reply_status_reason = ""
        if conv.pending_reply is msg:
            conv.pending_reply = None
        broadcast(
            {
                "type": "bot.reply_sent",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": msg.reply,
            }
        )

    async def approve_reply(self, wxid: str, edited_reply: str = "") -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv:
            return None
        if not conv.pending_reply:
            await asyncio.sleep(0)
        scheduled = self._reply_tasks.get(wxid)
        if scheduled and not scheduled.done():
            await asyncio.shield(scheduled)
        if not conv.pending_reply:
            return None
        pending = conv.pending_reply
        if pending.reply_status != "pending":
            return None

        if edited_reply:
            pending.reply = edited_reply

        try:
            outcome = await self._send_message(
                wxid,
                pending.reply,
                nickname=conv.nickname,
                guard_manual_conflict=False,
                search_terms=self._conv_mgr.get_search_terms(wxid),
            )
            if outcome.status != "sent":
                pending.reply_status_reason = outcome.reason
                return {"status": "error", "error": outcome.detail or outcome.reason}

            pending.reply_status = "sent"
            pending.reply_status_reason = ""
            if conv.pending_reply is pending:
                conv.pending_reply = None
            broadcast(
                {
                    "type": "bot.reply_sent",
                    "wxid": wxid,
                    "nickname": conv.nickname,
                    "reply": pending.reply,
                }
            )
            return {"status": "sent", "wxid": wxid, "reply": pending.reply}
        except Exception as exc:
            if isinstance(exc, SenderFailure):
                pending.reply_status_reason = exc.reason
                return {"status": "error", "error": exc.detail}
            pending.reply_status_reason = "send_failed"
            return {"status": "error", "error": str(exc)}

    def reject_reply(self, wxid: str) -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        pending = conv.pending_reply
        if pending.reply_status != "pending":
            return None

        pending.reply_status = "rejected"
        pending.reply_status_reason = ""
        if conv.pending_reply is pending:
            conv.pending_reply = None
        broadcast(
            {
                "type": "bot.reply_rejected",
                "wxid": wxid,
                "nickname": conv.nickname,
            }
        )
        return {"status": "rejected", "wxid": wxid}

    async def send_message_manual(self, wxid: str, content: str) -> dict:
        conv = self._conv_mgr.get_or_create(wxid)
        # 从 DB 查真实 nickname，搜索词只用 nickname
        nickname = conv.nickname
        search_terms = [t for t in conv.search_terms if not t.startswith("wxid_")]
        if not search_terms or nickname == wxid:
            try:
                from services.db import get_customer
                cust = get_customer(wxid)
                if cust:
                    nickname = cust.get("nickname") or nickname
                    if nickname and nickname != wxid:
                        search_terms = [nickname]
                        conv.nickname = nickname
                        conv.search_terms = search_terms
            except Exception:
                pass
        try:
            outcome = await self._send_message(
                wxid,
                content,
                nickname=nickname,
                guard_manual_conflict=False,
                search_terms=search_terms,
            )
            if outcome.status != "sent":
                return {"status": "error", "error": outcome.detail or outcome.reason}

            msg = BotMessage(
                id=str(uuid.uuid4()),
                wxid=wxid,
                content=content,
                is_from_customer=False,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                reply_status="sent",
            )
            conv.messages.append(msg)
            return {"status": "sent", "wxid": wxid, "content": content}
        except Exception as exc:
            if isinstance(exc, SenderFailure):
                return {"status": "error", "error": exc.detail}
            return {"status": "error", "error": str(exc)}

    async def _send_message(
        self,
        wxid: str,
        text: str,
        nickname: str = "",
        guard_manual_conflict: bool = True,
        search_terms: list[str] | None = None,
    ) -> SendOutcome:
        return await asyncio.to_thread(
            self._transport.send,
            wxid,
            text,
            nickname,
            guard_manual_conflict,
            search_terms,
        )


bot = WeChatBot()

subscribe_bot_events = subscribe
unsubscribe_bot_events = unsubscribe
