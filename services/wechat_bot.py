"""微信 AI 自动回复机器人服务

消息监控: 轮询 message_0.db mtime → 增量解密 → 检测新消息
LLM 回复: 复用 ChatOpenAI → customer_service prompt
消息发送: pywinauto UI 自动化
"""
import asyncio
import hashlib
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from adapters.db_layout import get_contact_db, get_message_dbs, get_db_layout
from adapters.extract import get_contact_nicknames
from api.decrypt_coordinator import ensure_decrypted
from config import settings


# ── 数据模型 ──────────────────────────────────────────────

class BotContactSettings:
    def __init__(self, wxid: str, mode: str = "", enabled: bool = True,
                 system_prompt_override: str = ""):
        self.wxid = wxid
        self.mode = mode or settings.BOT_DEFAULT_MODE
        self.enabled = enabled
        self.system_prompt_override = system_prompt_override


class BotMessage:
    def __init__(self, id: str, wxid: str, content: str,
                 is_from_customer: bool, timestamp: str,
                 reply: str = "", reply_status: str = ""):
        self.id = id
        self.wxid = wxid
        self.content = content
        self.is_from_customer = is_from_customer
        self.timestamp = timestamp
        self.reply = reply
        self.reply_status = reply_status  # pending / approved / sent / rejected


class BotConversation:
    def __init__(self, wxid: str, nickname: str = ""):
        self.wxid = wxid
        self.nickname = nickname
        self.messages: list[BotMessage] = []
        self.pending_reply: BotMessage | None = None
        self.last_seen_local_id: int = 0


# ── SSE 事件广播 ──────────────────────────────────────────

_sse_subscribers: list[asyncio.Queue] = []


def _broadcast_event(event: dict):
    for q in _sse_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscribe_bot_events() -> asyncio.Queue:
    q = asyncio.Queue(maxsize=200)
    _sse_subscribers.append(q)
    return q


def unsubscribe_bot_events(q: asyncio.Queue):
    if q in _sse_subscribers:
        _sse_subscribers.remove(q)


# ── 核心服务 ──────────────────────────────────────────────

class WeChatBot:
    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._conversations: dict[str, BotConversation] = {}
        self._contact_settings: dict[str, BotContactSettings] = {}
        self._nicknames: dict[str, str] = {}
        self._previous_mtimes: dict[str, float] = {}
        self._last_key_time: float = 0
        self._cached_keys: dict[str, str] = {}
        self._decrypted_paths: dict = {}
        self._start_time: float = 0
        self._version: str = ""
        self._self_wxid: str = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def start_time(self) -> float:
        return self._start_time

    @property
    def active_count(self) -> int:
        return len(self._conversations)

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._running else 0,
            "active_conversations": len(self._conversations),
            "pending_replies": sum(
                1 for c in self._conversations.values()
                if c.pending_reply and c.pending_reply.reply_status == "pending"
            ),
        }

    def get_conversations(self) -> list[dict]:
        result = []
        for conv in self._conversations.values():
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
        conv = self._conversations.get(wxid)
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
        conv = self._conversations.get(wxid)
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

    def update_contact_settings(self, wxid: str, mode: str | None = None,
                                 enabled: bool | None = None) -> dict:
        cs = self._contact_settings.get(wxid)
        if not cs:
            cs = BotContactSettings(wxid)
            self._contact_settings[wxid] = cs
        if mode is not None:
            cs.mode = mode
        if enabled is not None:
            cs.enabled = enabled
        return {"wxid": cs.wxid, "mode": cs.mode, "enabled": cs.enabled}

    def get_contact_settings_list(self) -> list[dict]:
        return [{
            "wxid": cs.wxid,
            "mode": cs.mode,
            "enabled": cs.enabled,
        } for cs in self._contact_settings.values()]

    # ── 生命周期 ──

    async def start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._monitor_loop())
        _broadcast_event({"type": "bot.status_change", "status": "running"})
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
        _broadcast_event({"type": "bot.status_change", "status": "stopped"})
        print("[Bot] 已停止")

    # ── 消息监控 ──

    async def _monitor_loop(self):
        try:
            # 初始化：解密 + 加载昵称 + 记录初始 local_id
            self._decrypted_paths = ensure_decrypted()
            self._load_nicknames()
            self._init_last_seen_ids()
        except Exception as e:
            _broadcast_event({"type": "bot.error", "error": str(e)})
            self._running = False
            return

        while self._running:
            try:
                await asyncio.to_thread(self._check_for_new_messages)
            except Exception as e:
                _broadcast_event({"type": "bot.error", "error": str(e)})
            await asyncio.sleep(settings.BOT_POLL_INTERVAL)

    def _load_nicknames(self):
        contact_db = get_contact_db(self._decrypted_paths)
        if contact_db:
            self._nicknames = get_contact_nicknames(contact_db)

    def _init_last_seen_ids(self):
        """记录当前每张消息表的最大 local_id，避免处理历史消息"""
        msg_dbs = get_message_dbs(self._decrypted_paths)
        for msg_db in msg_dbs:
            if not Path(msg_db).exists():
                continue
            try:
                conn = sqlite3.connect(msg_db)
                # 4.x: Msg_<hash> tables
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                ).fetchall()]
                for tbl in tables:
                    try:
                        row = conn.execute(f"SELECT MAX(local_id) FROM {tbl}").fetchone()
                        if row and row[0]:
                            conv = self._get_or_create_conv_by_table(tbl)
                            if conv:
                                conv.last_seen_local_id = row[0]
                    except Exception:
                        continue
                # 3.x: MSG table
                msg_table = None
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall():
                    if r[0].upper() == "MSG":
                        msg_table = r[0]
                        break
                if msg_table:
                    for wxid in self._nicknames:
                        try:
                            row = conn.execute(
                                f"SELECT MAX(localId) FROM {msg_table} WHERE StrTalker = ?",
                                (wxid,),
                            ).fetchone()
                            if row and row[0]:
                                conv = self._get_or_create_conv(wxid)
                                if conv:
                                    conv.last_seen_local_id = max(
                                        conv.last_seen_local_id, row[0]
                                    )
                        except Exception:
                            continue
                conn.close()
            except Exception:
                continue

    def _get_or_create_conv(self, wxid: str) -> BotConversation:
        if wxid not in self._conversations:
            self._conversations[wxid] = BotConversation(
                wxid=wxid,
                nickname=self._nicknames.get(wxid, wxid),
            )
        return self._conversations[wxid]

    def _get_or_create_conv_by_table(self, table_name: str) -> BotConversation | None:
        """通过 4.x 的 Msg_<hash> 表名反查 wxid"""
        table_hash = table_name[4:]
        for wxid, nick in self._nicknames.items():
            if hashlib.md5(wxid.encode()).hexdigest() == table_hash:
                return self._get_or_create_conv(wxid)
        return None

    def _check_for_new_messages(self):
        """检查是否有新消息（通过 mtime 变化检测）"""
        msg_dbs = get_message_dbs(self._decrypted_paths)
        for msg_db in msg_dbs:
            if not Path(msg_db).exists():
                continue
            current_mtime = Path(msg_db).stat().st_mtime
            prev_mtime = self._previous_mtimes.get(msg_db, 0)
            if current_mtime <= prev_mtime:
                continue
            self._previous_mtimes[msg_db] = current_mtime
            self._process_new_messages(msg_db)

    def _process_new_messages(self, msg_db: str):
        """处理单个数据库中的新消息"""
        try:
            conn = sqlite3.connect(msg_db)

            # 4.x: Msg_<hash> tables
            sender_map = self._get_sender_map(conn)
            self_rowid = self._get_self_rowid(conn)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()]
            for tbl in tables:
                conv = self._get_or_create_conv_by_table(tbl)
                if not conv:
                    continue
                try:
                    rows = conn.execute(
                        f"SELECT local_id, create_time, message_content, real_sender_id "
                        f"FROM {tbl} WHERE local_id > ? AND local_type = 1 "
                        f"ORDER BY local_id ASC",
                        (conv.last_seen_local_id,),
                    ).fetchall()
                    for row in rows:
                        local_id, create_time, content, sender_id = row
                        if not isinstance(content, str):
                            conv.last_seen_local_id = local_id
                            continue
                        sender_name = sender_map.get(sender_id, conv.wxid)
                        is_self = (self_rowid is not None and sender_id == self_rowid)
                        msg_time = datetime.fromtimestamp(create_time)
                        msg = BotMessage(
                            id=str(local_id),
                            wxid=conv.wxid,
                            content=content.strip(),
                            is_from_customer=not is_self,
                            timestamp=msg_time.strftime("%Y-%m-%d %H:%M"),
                        )
                        conv.messages.append(msg)
                        conv.last_seen_local_id = local_id
                        _broadcast_event({
                            "type": "bot.new_message",
                            "wxid": conv.wxid,
                            "nickname": conv.nickname,
                            "content": msg.content,
                            "is_from_customer": msg.is_from_customer,
                            "timestamp": msg.timestamp,
                        })
                        if msg.is_from_customer:
                            self._on_new_customer_message(conv, msg)
                except Exception:
                    continue

            # 3.x: MSG table
            msg_table = None
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall():
                if r[0].upper() == "MSG":
                    msg_table = r[0]
                    break
            if msg_table:
                for wxid in self._nicknames:
                    conv = self._get_or_create_conv(wxid)
                    try:
                        rows = conn.execute(
                            f"SELECT localId, CreateTime, StrContent FROM {msg_table} "
                            f"WHERE StrTalker = ? AND Type = 1 AND localId > ? "
                            f"ORDER BY localId ASC",
                            (wxid, conv.last_seen_local_id),
                        ).fetchall()
                        for row in rows:
                            local_id, create_time, content = row
                            if not content:
                                conv.last_seen_local_id = local_id
                                continue
                            msg_time = datetime.fromtimestamp(create_time)
                            msg = BotMessage(
                                id=str(local_id),
                                wxid=wxid,
                                content=content.strip(),
                                is_from_customer=True,
                                timestamp=msg_time.strftime("%Y-%m-%d %H:%M"),
                            )
                            conv.messages.append(msg)
                            conv.last_seen_local_id = local_id
                            _broadcast_event({
                                "type": "bot.new_message",
                                "wxid": wxid,
                                "nickname": conv.nickname,
                                "content": msg.content,
                                "is_from_customer": True,
                                "timestamp": msg.timestamp,
                            })
                            self._on_new_customer_message(conv, msg)
                    except Exception:
                        continue

            conn.close()
        except Exception as e:
            print(f"[Bot] 读取消息出错: {e}")

    def _get_sender_map(self, conn) -> dict[int, str]:
        result = {}
        try:
            for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
                result[row[0]] = row[1]
        except Exception:
            pass
        return result

    def _get_self_rowid(self, conn) -> int | None:
        try:
            row = conn.execute(
                "SELECT rowid FROM Name2Id WHERE is_session = 0 LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    # ── LLM 回复 ──

    def _on_new_customer_message(self, conv: BotConversation, msg: BotMessage):
        cs = self._contact_settings.get(conv.wxid)
        mode = cs.mode if cs and cs.enabled else settings.BOT_DEFAULT_MODE

        # 生成回复
        reply = self._generate_reply(conv)
        if not reply:
            return

        msg.reply = reply
        msg.reply_status = "pending"
        conv.pending_reply = msg

        _broadcast_event({
            "type": "bot.reply_generated",
            "wxid": conv.wxid,
            "nickname": conv.nickname,
            "reply": reply,
            "mode": mode,
        })

        if mode == "auto":
            self._do_send(conv, msg)

    def _generate_reply(self, conv: BotConversation) -> str:
        try:
            prompts = self._load_prompts()
            cs_prompt = prompts.get("customer_service", {})
            system_text = cs_prompt.get("system", "")
            cs_settings = self._contact_settings.get(conv.wxid)
            if cs_settings and cs_settings.system_prompt_override:
                system_text = cs_settings.system_prompt_override

            user_template = cs_prompt.get("user_template", "")
            context_msgs = conv.messages[-settings.BOT_CONTEXT_MESSAGES:]
            chat_history = "\n".join(
                f"[{'客户' if m.is_from_customer else '我方'}] {m.content}"
                for m in context_msgs[:-1]
            ) if context_msgs else "（无历史记录）"

            latest = context_msgs[-1].content if context_msgs else ""
            user_text = user_template.format(
                customer_info=f"昵称: {conv.nickname}\n微信号: {conv.wxid}",
                chat_history=chat_history,
                latest_message=latest,
            ) if user_template else latest

            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                openai_api_key=settings.LLM_API_KEY,
                openai_api_base=settings.LLM_BASE_URL,
                temperature=0.7,
                max_tokens=200,
            )
            result = llm.invoke([
                SystemMessage(content=system_text),
                HumanMessage(content=user_text),
            ])
            return result.content.strip()
        except Exception as e:
            print(f"[Bot] LLM 生成回复出错: {e}")
            return ""

    def _load_prompts(self) -> dict:
        prompts_path = Path(__file__).parent.parent / settings.PROMPTS_FILE
        with open(prompts_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # ── 消息发送 ──

    def _do_send(self, conv: BotConversation, msg: BotMessage):
        """自动模式：直接发送回复"""
        try:
            asyncio.get_event_loop().run_until_complete(
                self._send_message(conv.wxid, msg.reply)
            )
            msg.reply_status = "sent"
            conv.pending_reply = None
            _broadcast_event({
                "type": "bot.reply_sent",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "reply": msg.reply,
            })
        except Exception as e:
            msg.reply_status = "error"
            _broadcast_event({
                "type": "bot.error",
                "error": f"发送失败: {e}",
                "wxid": conv.wxid,
            })

    async def approve_reply(self, wxid: str, edited_reply: str = "") -> dict | None:
        """半自动模式：审批通过并发送"""
        conv = self._conversations.get(wxid)
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
            _broadcast_event({
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
        """半自动模式：拒绝回复"""
        conv = self._conversations.get(wxid)
        if not conv or not conv.pending_reply:
            return None
        p = conv.pending_reply
        if p.reply_status != "pending":
            return None

        p.reply_status = "rejected"
        conv.pending_reply = None
        _broadcast_event({
            "type": "bot.reply_rejected",
            "wxid": wxid,
            "nickname": conv.nickname,
        })
        return {"status": "rejected", "wxid": wxid}

    async def send_message_manual(self, wxid: str, content: str) -> dict:
        """手动发消息"""
        conv = self._get_or_create_conv(wxid)
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
        """通过 pywinauto 自动化发送消息"""
        await asyncio.to_thread(self._send_via_pywinauto, wxid, text)

    def _send_via_pywinauto(self, wxid: str, text: str):
        """pywinauto UI 自动化：搜索联系人 → 输入 → 发送"""
        from pywinauto import Application

        # 查找微信窗口
        try:
            app = Application().connect(path="Weixin.exe")
        except Exception:
            raise RuntimeError("未找到微信窗口，请确保微信已登录")

        # 获取主窗口
        main_window = None
        for win in app.windows():
            if win.element_info.class_name == "WeChatMainWndForPC":
                main_window = win
                break
        if not main_window:
            # fallback: 取最前面的窗口
            try:
                main_window = app.top_window()
            except Exception:
                raise RuntimeError("无法获取微信主窗口")

        main_window.set_focus()

        # 使用快捷键 Ctrl+F 搜索联系人
        import pywinauto.keyboard as kb
        kb.send_keys('^f')
        time.sleep(0.5)

        # 输入 wxid 或昵称搜索
        search_edit = None
        try:
            search_edit = main_window.child_window(
                auto_id="SearchLineEdit", control_type="Edit"
            )
        except Exception:
            pass

        if search_edit:
            search_edit.set_text(wxid)
        else:
            kb.send_keys(wxid)

        time.sleep(1)

        # 回车选中搜索结果
        kb.send_keys('{ENTER}')
        time.sleep(0.5)

        # 在输入框中输入消息
        msg_edit = None
        try:
            msg_edit = main_window.child_window(
                auto_id="ChatEditWndForPC", control_type="Edit"
            )
        except Exception:
            pass

        if msg_edit:
            msg_edit.set_text(text)
        else:
            kb.send_keys(text)

        time.sleep(0.3)

        # 发送
        kb.send_keys('{ENTER}')
        time.sleep(0.3)

        # 按 Esc 关闭搜索
        kb.send_keys('{ESC}')


# ── 全局单例 ──

bot = WeChatBot()
