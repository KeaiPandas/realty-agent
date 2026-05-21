"""微信 AI 自动回复机器人 — 编排层

组合 monitor / responder / sender / conversation / events 子模块。
对外接口保持与原 wechat_bot.py 兼容。
"""
import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path

from config import settings

from services.bot.models import BotMessage, BotConversation
from services.bot.conversation import ConversationManager
from services.bot.events import broadcast, subscribe, unsubscribe
from services.bot.monitor import Monitor
from services.bot.responder import generate_reply
from services.bot.sender import PywinautoTransport


class WeChatBot:
    def __init__(self, transport=None):
        self._running = False
        self._task: asyncio.Task | None = None
        self._start_time: float = 0
        self._conv_mgr = ConversationManager()
        self._transport = transport or PywinautoTransport()
        self._monitor = Monitor(self._conv_mgr, on_customer_msg=self._on_customer_message)

    # ── 公共属性 ──

    @property
    def running(self) -> bool:
        return self._running

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def active_count(self) -> int:
        return self._conv_mgr.active_count

    # ── 状态查询 ──

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._running else 0,
            "active_conversations": self._conv_mgr.active_count,
            "pending_replies": sum(
                1 for c in self._conv_mgr.conversations.values()
                if c.pending_reply and c.pending_reply.reply_status == "pending"
            ),
        }

    def get_conversations(self) -> list[dict]:
        result = []
        for conv in self._conv_mgr.conversations.values():
            pending = conv.pending_reply
            result.append({
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "message_count": len(conv.messages),
                "last_message_time": conv.messages[-1].timestamp if conv.messages else "",
                "pending_reply": {
                    "id": pending.id,
                    "content": pending.content,
                    "reply": pending.reply,
                    "reply_status": pending.reply_status,
                    "timestamp": pending.timestamp,
                } if pending and pending.reply_status == "pending" else None,
            })
        return result

    def get_messages(self, wxid: str, limit: int = 50) -> list[dict]:
        conv = self._conv_mgr.get(wxid)
        if not conv:
            return []
        msgs = conv.messages[-limit:]
        return [{
            "id": m.id,
            "wxid": m.wxid,
            "content": m.content,
            "is_from_customer": m.is_from_customer,
            "timestamp": m.timestamp,
            "reply": m.reply,
            "reply_status": m.reply_status,
        } for m in msgs]

    def get_pending(self, wxid: str) -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        p = conv.pending_reply
        if p.reply_status != "pending":
            return None
        return {
            "id": p.id,
            "wxid": p.wxid,
            "content": p.content,
            "reply": p.reply,
            "reply_status": p.reply_status,
            "timestamp": p.timestamp,
        }

    # ── 联系人设置 ──

    def update_contact_settings(self, wxid: str, mode: str | None = None,
                                 enabled: bool | None = None) -> dict:
        return self._conv_mgr.update_settings(wxid, mode, enabled)

    def get_contact_settings_list(self) -> list[dict]:
        return self._conv_mgr.get_settings_list()

    # ── 生命周期 ──

    async def start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._monitor_loop())
        broadcast({"type": "bot.status_change", "status": "running"})
        print("[Bot] 已启动")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        broadcast({"type": "bot.status_change", "status": "stopped"})
        print("[Bot] 已停止")

    async def _monitor_loop(self):
        try:
            self._monitor.initialize()
        except Exception as e:
            broadcast({"type": "bot.error", "error": str(e)})
            self._running = False
            return

        while self._running:
            try:
                await asyncio.to_thread(self._monitor.check)
            except Exception as e:
                broadcast({"type": "bot.error", "error": str(e)})
            await asyncio.sleep(settings.BOT_POLL_INTERVAL)

    # ── 回复路由 ──

    def _on_customer_message(self, conv: BotConversation, msg: BotMessage):
        """Monitor 检测到客户消息时的回调"""
        cs = self._conv_mgr.get_settings(conv.wxid)
        mode = cs.mode if cs and cs.enabled else settings.BOT_DEFAULT_MODE

        reply = generate_reply(conv, self._conv_mgr)
        if not reply:
            return

        msg.reply = reply
        msg.reply_status = "pending"
        conv.pending_reply = msg

        broadcast({
            "type": "bot.reply_generated",
            "wxid": conv.wxid,
            "nickname": conv.nickname,
            "reply": reply,
            "mode": mode,
        })

        if mode == "auto":
            self._do_send(conv, msg)

    def _do_send(self, conv: BotConversation, msg: BotMessage):
        try:
            asyncio.get_event_loop().run_until_complete(
                self._send_message(conv.wxid, msg.reply)
            )
            msg.reply_status = "sent"
            conv.pending_reply = None
            broadcast({
                "type": "bot.reply_sent",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": msg.reply,
            })
        except Exception as e:
            msg.reply_status = "error"
            broadcast({
                "type": "bot.error",
                "error": f"发送失败: {e}",
                "wxid": conv.wxid,
            })

    # ── 审批 ──

    async def approve_reply(self, wxid: str, edited_reply: str = "") -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        p = conv.pending_reply
        if p.reply_status != "pending":
            return None

        if edited_reply:
            p.reply = edited_reply

        try:
            await self._send_message(wxid, p.reply)
            p.reply_status = "sent"
            conv.pending_reply = None
            broadcast({
                "type": "bot.reply_sent",
                "wxid": wxid,
                "nickname": conv.nickname,
                "reply": p.reply,
            })
            return {"status": "sent", "wxid": wxid, "reply": p.reply}
        except Exception as e:
            p.reply_status = "error"
            return {"status": "error", "error": str(e)}

    def reject_reply(self, wxid: str) -> dict | None:
        conv = self._conv_mgr.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        p = conv.pending_reply
        if p.reply_status != "pending":
            return None

        p.reply_status = "rejected"
        conv.pending_reply = None
        broadcast({
            "type": "bot.reply_rejected",
            "wxid": wxid,
            "nickname": conv.nickname,
        })
        return {"status": "rejected", "wxid": wxid}

    # ── 手动发送 ──

    async def send_message_manual(self, wxid: str, content: str) -> dict:
        conv = self._conv_mgr.get_or_create(wxid)
        try:
            await self._send_message(wxid, content)
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
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _send_message(self, wxid: str, text: str):
        await asyncio.to_thread(self._transport.send, wxid, text)


# ── 全局单例 ──

bot = WeChatBot()

# 兼容旧导入路径
subscribe_bot_events = subscribe
unsubscribe_bot_events = unsubscribe
