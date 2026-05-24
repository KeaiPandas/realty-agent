"""Bot 消息监控 — mtime 轮询 + 增量解密 + 新消息检测"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from services.sync.db_layout import get_contact_db, get_message_dbs, get_db_layout
from services.sync.extract import get_contact_nicknames, get_contact_profiles
from api.decrypt_coordinator import ensure_decrypted
from config import settings

from services.bot.models import BotMessage, BotConversation
from services.bot.conversation import ConversationManager
from services.bot.events import broadcast
from services.bot.responder import is_nonsense, is_blocked

# 客户消息回调类型: (conv, msg) → None
OnCustomerMessage = Callable[[BotConversation, BotMessage], None]


class Monitor:
    def __init__(self, conv_mgr: ConversationManager,
                 on_customer_msg: OnCustomerMessage | None = None):
        self._conv_mgr = conv_mgr
        self._on_customer_msg = on_customer_msg
        # 加密源文件 mtime 缓存
        self._source_mtimes: dict[str, float] = {}
        # 加密→解密 路径映射
        self._src_to_dec: dict[str, str] = {}
        # 解密密钥缓存
        self._cached_keys: dict[str, str] = {}
        self._decrypted_paths: dict = {}
        self._version: str = ""
        self._wechat_dir: Path | None = None
        self._wxauto_client = None
        self._seen_wxauto_ids: dict[str, set[str]] = {}
        self._wxauto_listener_terms: set[str] = set()

    def initialize(self):
        """初始化: 解密数据库、建立映射、记录游标"""
        from services.sync.decrypt import _resolve_version

        self._version = _resolve_version()
        if self._version == "3.x":
            self._initialize_wxauto_monitor()
            self._check_wxauto_messages()
            print("[Bot] 3.x monitor initialized via wxauto unread polling")
            return

        self._decrypted_paths = ensure_decrypted()
        self._load_nicknames()
        self._build_source_mapping()

        for src in self._src_to_dec:
            src_path = Path(src)
            if src_path.exists():
                self._source_mtimes[src] = src_path.stat().st_mtime

        self._init_last_seen_ids()
        self._catch_up_existing_messages()
        print(f"[Bot] 监控 {len(self._src_to_dec)} 个加密源文件")

    def check(self):
        """检查加密源文件 mtime 变化 → 重新解密 → 处理新消息"""
        if self._version == "3.x":
            self._check_wxauto_messages()
            return

        for src_str, dec_str in self._src_to_dec.items():
            src_path = Path(src_str)
            if not src_path.exists():
                continue

            current_mtime = src_path.stat().st_mtime
            prev_mtime = self._source_mtimes.get(src_str, 0)

            if current_mtime <= prev_mtime:
                continue

            print(f"[Bot] 检测到源文件变化: {src_path.name}")
            self._source_mtimes[src_str] = current_mtime

            try:
                self._redecrypt(src_path, Path(dec_str))
            except Exception as e:
                print(f"[Bot] 重新解密失败: {e}")
                continue

            self._process_new_messages(dec_str)

    # ── 内部方法 ──

    def _build_source_mapping(self):
        from services.sync.decrypt import _resolve_version

        self._version = self._version or _resolve_version()
        wechat_dir = Path(settings.WECHAT_DATA_DIR)
        self._wechat_dir = wechat_dir

        source_db_files = get_db_layout(wechat_dir, self._version)
        dec_dir = wechat_dir / "decrypted"

        self._src_to_dec = {}
        for name, src_path in source_db_files.items():
            if not (name.startswith("message_") or name in ("ChatMsg",) or name.startswith("MSG")):
                continue
            dec_path = dec_dir / f"{name}.db"
            if dec_path.exists():
                self._src_to_dec[str(src_path)] = str(dec_path)

    def _load_nicknames(self):
        contact_db = get_contact_db(self._decrypted_paths)
        if contact_db:
            profiles = get_contact_profiles(contact_db)
            if profiles:
                self._conv_mgr.profiles = profiles
            else:
                self._conv_mgr.nicknames = get_contact_nicknames(contact_db)

    def _init_last_seen_ids(self):
        msg_dbs = get_message_dbs(self._decrypted_paths)
        for msg_db in msg_dbs:
            if not Path(msg_db).exists():
                continue
            try:
                conn = sqlite3.connect(msg_db)
                # 4.x
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                ).fetchall()]
                for tbl in tables:
                    try:
                        row = conn.execute(f"SELECT MAX(local_id) FROM {tbl}").fetchone()
                        if row and row[0]:
                            conv = self._conv_mgr.get_by_table(tbl)
                            if conv and conv.last_seen_local_id <= 0 and not conv.messages:
                                conv.last_seen_local_id = row[0]
                    except Exception:
                        continue
                # 3.x
                msg_table = None
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall():
                    if r[0].upper() == "MSG":
                        msg_table = r[0]
                        break
                if msg_table:
                    for wxid in self._conv_mgr.nicknames:
                        try:
                            row = conn.execute(
                                f"SELECT MAX(localId) FROM {msg_table} WHERE StrTalker = ?",
                                (wxid,),
                            ).fetchone()
                            if row and row[0]:
                                conv = self._conv_mgr.get_or_create(wxid)
                                if conv and conv.last_seen_local_id <= 0 and not conv.messages:
                                    conv.last_seen_local_id = max(
                                        conv.last_seen_local_id, row[0]
                                    )
                        except Exception:
                            continue
                conn.close()
            except Exception:
                continue

    def _catch_up_existing_messages(self):
        for msg_db in get_message_dbs(self._decrypted_paths):
            if not Path(msg_db).exists():
                continue
            try:
                self._process_new_messages(msg_db)
            except Exception:
                continue

    def _redecrypt(self, src_path: Path, dec_path: Path):
        from services.sync.decrypt import _extract_keys_v4, _decrypt_db_v3, _decrypt_db_v4, _get_wx_info_v3

        if self._version == "4.x":
            if not self._cached_keys:
                source_db_files = get_db_layout(self._wechat_dir, self._version)
                self._cached_keys = _extract_keys_v4(source_db_files)

            db_name = src_path.stem
            key = self._cached_keys.get(db_name)
            if not key:
                raise RuntimeError(f"未找到 {db_name} 的密钥")
            _decrypt_db_v4(str(src_path), key, str(dec_path))
        else:
            if not self._cached_keys:
                wx_info = _get_wx_info_v3()
                if isinstance(wx_info, list) and wx_info:
                    self._cached_keys["_v3_key"] = wx_info[0].get("key", "")
            key = self._cached_keys.get("_v3_key", "")
            if key:
                _decrypt_db_v3(str(src_path), key, str(dec_path))

    def _process_new_messages(self, msg_db: str):
        try:
            conn = sqlite3.connect(msg_db)
            sender_map = self._get_sender_map(conn)
            self_rowid = self._get_self_rowid(conn)

            # 4.x
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()]
            for tbl in tables:
                conv = self._conv_mgr.get_by_table(tbl)
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
                        content = content.strip()
                        if is_nonsense(content) or is_blocked(content):
                            conv.last_seen_local_id = local_id
                            continue
                        is_self = (self_rowid is not None and sender_id == self_rowid)
                        msg_time = datetime.fromtimestamp(create_time)
                        msg = BotMessage(
                            id=str(local_id),
                            wxid=conv.wxid,
                            content=content,
                            is_from_customer=not is_self,
                            timestamp=msg_time.strftime("%Y-%m-%d %H:%M"),
                        )
                        conv.messages.append(msg)
                        conv.last_seen_local_id = local_id
                        broadcast({
                            "type": "bot.new_message",
                            "wxid": conv.wxid,
                            "nickname": conv.nickname,
                            "content": msg.content,
                            "is_from_customer": msg.is_from_customer,
                            "timestamp": msg.timestamp,
                        })
                        if msg.is_from_customer and self._on_customer_msg:
                            self._on_customer_msg(conv, msg)
                except Exception:
                    continue

            # 3.x
            msg_table = None
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall():
                if r[0].upper() == "MSG":
                    msg_table = r[0]
                    break
            if msg_table:
                for wxid in self._conv_mgr.nicknames:
                    conv = self._conv_mgr.get_or_create(wxid)
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
                            content = content.strip()
                            if is_nonsense(content) or is_blocked(content):
                                conv.last_seen_local_id = local_id
                                continue
                            msg_time = datetime.fromtimestamp(create_time)
                            msg = BotMessage(
                                id=str(local_id),
                                wxid=wxid,
                                content=content,
                                is_from_customer=True,
                                timestamp=msg_time.strftime("%Y-%m-%d %H:%M"),
                            )
                            conv.messages.append(msg)
                            conv.last_seen_local_id = local_id
                            broadcast({
                                "type": "bot.new_message",
                                "wxid": wxid,
                                "nickname": conv.nickname,
                                "content": msg.content,
                                "is_from_customer": True,
                                "timestamp": msg.timestamp,
                            })
                            if self._on_customer_msg:
                                self._on_customer_msg(conv, msg)
                    except Exception:
                        continue

            conn.close()
        except Exception as e:
            print(f"[Bot] 读取消息出错: {e}")

    def _initialize_wxauto_monitor(self):
        try:
            from wxauto import WeChat
        except ImportError as exc:
            raise RuntimeError("wxauto is required for WeChat 3.x monitoring") from exc

        self._wxauto_client = WeChat()
        self._ensure_wxauto_listeners()

    def _check_wxauto_messages(self):
        if self._wxauto_client is None:
            self._initialize_wxauto_monitor()
        self._ensure_wxauto_listeners()

        try:
            session_messages = self._wxauto_client.GetAllNewMessage(max_round=5) or {}
        except Exception as exc:
            raise RuntimeError(f"wxauto unread polling failed: {exc}") from exc

        for who, messages in session_messages.items():
            wxid = self._resolve_contact_key(who)
            conv = self._conv_mgr.get_or_create(wxid)
            if who and conv.nickname == conv.wxid:
                conv.nickname = who
            for item in messages or []:
                self._process_wxauto_message(conv, who, item)

        listened_messages = {}
        get_listen_message = getattr(self._wxauto_client, "GetListenMessage", None)
        if callable(get_listen_message):
            try:
                listened_messages = get_listen_message() or {}
            except Exception as exc:
                raise RuntimeError(f"wxauto listener polling failed: {exc}") from exc

        for chat_ref, messages in listened_messages.items():
            who = getattr(chat_ref, "who", "") or str(chat_ref)
            wxid = self._resolve_contact_key(who)
            conv = self._conv_mgr.get_or_create(wxid)
            if who and conv.nickname == conv.wxid:
                conv.nickname = who
            for item in messages or []:
                self._process_wxauto_message(conv, who, item)

    def _ensure_wxauto_listeners(self):
        if self._wxauto_client is None:
            return

        targets: list[str] = []
        try:
            current_chat = (self._wxauto_client.CurrentChat() or "").strip()
        except Exception:
            current_chat = ""
        if current_chat:
            targets.append(current_chat)

        for conv in self._conv_mgr.conversations.values():
            targets.extend(conv.search_terms or [conv.nickname, conv.wxid])

        for item in self._conv_mgr.get_settings_list():
            targets.extend(self._conv_mgr.get_search_terms(item["wxid"]))

        deduped: list[str] = []
        seen: set[str] = set()
        for target in targets:
            value = (target or "").strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen or key in self._wxauto_listener_terms:
                continue
            seen.add(key)
            deduped.append(value)

        for target in deduped:
            try:
                self._wxauto_client.AddListenChat(target)
                self._wxauto_listener_terms.add(target.casefold())
            except Exception:
                continue

    def _process_wxauto_message(self, conv: BotConversation, who: str, item):
        msg_type = str(getattr(item, "type", "") or "").lower()
        if msg_type and msg_type not in {"friend"}:
            return

        content = str(getattr(item, "content", "") or "").strip()
        if not content or is_nonsense(content) or is_blocked(content):
            return

        message_id = self._wxauto_message_id(conv.wxid, who, item, content)
        if self._has_seen_wxauto_message(conv.wxid, message_id):
            return

        msg = BotMessage(
            id=message_id,
            wxid=conv.wxid,
            content=content,
            is_from_customer=True,
            timestamp=self._wxauto_message_timestamp(item),
        )
        conv.messages.append(msg)
        broadcast(
            {
                "type": "bot.new_message",
                "wxid": conv.wxid,
                "nickname": conv.nickname,
                "content": msg.content,
                "is_from_customer": True,
                "timestamp": msg.timestamp,
            }
        )
        if self._on_customer_msg:
            self._on_customer_msg(conv, msg)

    def _resolve_contact_key(self, session_name: str) -> str:
        target = (session_name or "").strip()
        if not target:
            return session_name
        folded = target.casefold()

        for wxid, profile in self._conv_mgr.profiles.items():
            candidates = [
                profile.get("wxid", ""),
                profile.get("display_name", ""),
                profile.get("remark", ""),
                profile.get("nickname", ""),
                profile.get("alias", ""),
            ]
            candidates.extend(profile.get("search_terms") or [])
            if any((candidate or "").strip().casefold() == folded for candidate in candidates):
                return wxid

        for wxid, nickname in self._conv_mgr.nicknames.items():
            if (nickname or "").strip().casefold() == folded:
                return wxid

        return target

    def _has_seen_wxauto_message(self, wxid: str, message_id: str) -> bool:
        seen = self._seen_wxauto_ids.setdefault(wxid, set())
        if message_id in seen:
            return True
        seen.add(message_id)
        if len(seen) > 200:
            self._seen_wxauto_ids[wxid] = set(list(seen)[-100:])
        return False

    @staticmethod
    def _wxauto_message_id(wxid: str, who: str, item, content: str) -> str:
        raw_id = getattr(item, "id", None)
        if raw_id not in (None, ""):
            return f"wxauto:{wxid}:{raw_id}"
        sender = str(getattr(item, "sender", "") or "")
        digest = hashlib.md5(f"{wxid}|{who}|{sender}|{content}".encode("utf-8")).hexdigest()
        return f"wxauto:{wxid}:{digest}"

    @staticmethod
    def _wxauto_message_timestamp(item) -> str:
        raw_time = getattr(item, "time", None) or getattr(item, "timestamp", None)
        if isinstance(raw_time, datetime):
            return raw_time.strftime("%Y-%m-%d %H:%M")
        if isinstance(raw_time, str) and raw_time.strip():
            return raw_time.strip()
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _get_sender_map(conn) -> dict[int, str]:
        result = {}
        try:
            for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
                result[row[0]] = row[1]
        except Exception:
            pass
        return result

    @staticmethod
    def _get_self_rowid(conn) -> int | None:
        try:
            row = conn.execute(
                "SELECT rowid FROM Name2Id WHERE is_session = 0 LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None
