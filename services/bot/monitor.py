"""Bot 消息监控 — mtime 轮询 + 增量解密 + 新消息检测"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from services.sync.db_layout import get_contact_db, get_message_dbs, get_db_layout
from services.sync.extract import get_contact_nicknames
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

    def initialize(self):
        """初始化: 解密数据库、建立映射、记录游标"""
        self._decrypted_paths = ensure_decrypted()
        self._load_nicknames()
        self._build_source_mapping()

        for src in self._src_to_dec:
            src_path = Path(src)
            if src_path.exists():
                self._source_mtimes[src] = src_path.stat().st_mtime

        self._init_last_seen_ids()
        print(f"[Bot] 监控 {len(self._src_to_dec)} 个加密源文件")

    def check(self):
        """检查加密源文件 mtime 变化 → 重新解密 → 处理新消息"""
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

        self._version = _resolve_version()
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
                            if conv:
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
                                if conv:
                                    conv.last_seen_local_id = max(
                                        conv.last_seen_local_id, row[0]
                                    )
                        except Exception:
                            continue
                conn.close()
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
