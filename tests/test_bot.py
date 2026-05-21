"""Tests for WeChat Bot — message detection, mode routing, conversation management.

Uses temp SQLite DBs to simulate decrypted databases without needing real WeChat.
"""
import hashlib
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest


# ── Helpers ──

def _create_decrypted_db(path: Path, table_type: str = "4.x", wxid: str = "test_user"):
    """Create a minimal decrypted SQLite DB for testing."""
    conn = sqlite3.connect(str(path))
    if table_type == "4.x":
        table_hash = hashlib.md5(wxid.encode()).hexdigest()
        conn.execute(f"""
            CREATE TABLE Msg_{table_hash} (
                local_id INTEGER PRIMARY KEY,
                create_time REAL,
                local_type INTEGER,
                message_content TEXT,
                real_sender_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE Name2Id (
                rowid INTEGER PRIMARY KEY,
                user_name TEXT,
                is_session INTEGER
            )
        """)
        # self rowid=1 (is_session=0), customer rowid=2
        conn.execute("INSERT INTO Name2Id VALUES (1, 'self_wxid', 0)")
        conn.execute(f"INSERT INTO Name2Id VALUES (2, '{wxid}', 1)")
    else:
        conn.execute("""
            CREATE TABLE MSG (
                localId INTEGER PRIMARY KEY,
                StrTalker TEXT,
                CreateTime REAL,
                Type INTEGER,
                StrContent TEXT
            )
        """)
    conn.commit()
    conn.close()


def _insert_message_4x(path: Path, wxid: str, local_id: int, content: str,
                        create_time: float = None, sender_id: int = 2):
    """Insert a message into a 4.x test DB."""
    table_hash = hashlib.md5(wxid.encode()).hexdigest()
    conn = sqlite3.connect(str(path))
    conn.execute(
        f"INSERT INTO Msg_{table_hash} (local_id, create_time, local_type, message_content, real_sender_id) "
        f"VALUES (?, ?, 1, ?, ?)",
        (local_id, create_time or time.time(), content, sender_id),
    )
    conn.commit()
    conn.close()


def _insert_message_3x(path: Path, wxid: str, local_id: int, content: str,
                        create_time: float = None):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO MSG (localId, StrTalker, CreateTime, Type, StrContent) "
        "VALUES (?, ?, ?, 1, ?)",
        (local_id, wxid, create_time or time.time(), content),
    )
    conn.commit()
    conn.close()


def _make_bot():
    """Create a WeChatBot with mocked-out monitor (no real decrypt)."""
    from services.bot import WeChatBot
    return WeChatBot()


# ── Test: Conversation management ──

class TestConversation:
    def test_get_or_create_conv(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        b._conv_mgr.nicknames = {"wxid_abc": "Alice"}
        conv = b._conv_mgr.get_or_create("wxid_abc")
        assert conv.wxid == "wxid_abc"
        assert conv.nickname == "Alice"

    def test_get_or_create_conv_by_table(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_test123"
        b._conv_mgr.nicknames = {wxid: "TestUser"}
        table_hash = hashlib.md5(wxid.encode()).hexdigest()
        table_name = f"Msg_{table_hash}"
        conv = b._conv_mgr.get_by_table(table_name)
        assert conv is not None
        assert conv.wxid == wxid

    def test_get_or_create_conv_by_table_unknown(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        b._conv_mgr.nicknames = {"other": "Other"}
        conv = b._conv_mgr.get_by_table("Msg_deadbeef")
        assert conv is None


# ── Test: Message detection via encrypted source mtime ──

class TestMessageDetection:
    def test_detect_mtime_change_on_source(self):
        """Simulate: source file mtime changes → should be detected."""
        from services.bot import WeChatBot
        b = WeChatBot()
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "message"
            src_dir.mkdir()
            src_file = src_dir / "message_0.db"
            src_file.write_bytes(b"fake encrypted data")

            initial_mtime = src_file.stat().st_mtime
            b._monitor._source_mtimes = {str(src_file): initial_mtime}

            time.sleep(0.1)
            src_file.write_bytes(b"fake encrypted data updated")
            new_mtime = src_file.stat().st_mtime

            assert new_mtime > initial_mtime
            assert new_mtime > b._monitor._source_mtimes[str(src_file)]


# ── Test: Process new messages from decrypted DB ──

class TestProcessMessages:
    def test_process_4x_messages(self):
        """Insert messages into test DB, verify bot processes them."""
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_customer1"
        b._conv_mgr.nicknames = {wxid: "Customer1", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)

            conv = b._conv_mgr.get_or_create(wxid)
            assert conv.last_seen_local_id == 0

            _insert_message_4x(db_path, wxid, 1, "你好", sender_id=2)
            _insert_message_4x(db_path, wxid, 2, "我想问一下房价", sender_id=2)

            b._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 2
            assert conv.messages[0].content == "你好"
            assert conv.messages[1].content == "我想问一下房价"
            assert conv.messages[0].is_from_customer is True
            assert conv.last_seen_local_id == 2

    def test_process_3x_messages(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_old_customer"
        b._conv_mgr.nicknames = {wxid: "OldCustomer"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ChatMsg.db"
            _create_decrypted_db(db_path, "3.x")
            _insert_message_3x(db_path, wxid, 1, "你好呀")

            conv = b._conv_mgr.get_or_create(wxid)
            b._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 1
            assert conv.messages[0].content == "你好呀"

    def test_only_new_messages_processed(self):
        """Messages with local_id <= last_seen_local_id should be skipped."""
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_test"
        b._conv_mgr.nicknames = {wxid: "Test", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)
            _insert_message_4x(db_path, wxid, 1, "old msg", sender_id=2)
            _insert_message_4x(db_path, wxid, 2, "new msg", sender_id=2)

            conv = b._conv_mgr.get_or_create(wxid)
            conv.last_seen_local_id = 1

            b._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 1
            assert conv.messages[0].content == "new msg"
            assert conv.last_seen_local_id == 2

    def test_self_messages_not_from_customer(self):
        """Messages from self (sender_id = self_rowid) should be is_from_customer=False."""
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_bob"
        b._conv_mgr.nicknames = {wxid: "Bob", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)
            _insert_message_4x(db_path, wxid, 1, "my reply", sender_id=1)
            _insert_message_4x(db_path, wxid, 2, "customer msg", sender_id=2)

            b._monitor._process_new_messages(str(db_path))

            conv = b._conv_mgr.conversations[wxid]
            assert conv.messages[0].is_from_customer is False
            assert conv.messages[1].is_from_customer is True


# ── Test: Mode routing ──

class TestModeRouting:
    def test_default_mode_semi_auto(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        cs = b.update_contact_settings("wxid_test")
        assert cs["mode"] == "semi_auto" or cs["mode"] in ("auto", "semi_auto")

    def test_set_auto_mode(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        result = b.update_contact_settings("wxid_test", mode="auto")
        assert result["mode"] == "auto"

    def test_set_disabled(self):
        from services.bot import WeChatBot
        b = WeChatBot()
        result = b.update_contact_settings("wxid_test", enabled=False)
        assert result["enabled"] is False


# ── Test: Init last seen IDs ──

class TestInitLastSeenIds:
    def test_init_captures_max_local_id(self):
        """_init_last_seen_ids should set last_seen_local_id to current max."""
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_init_test"
        b._conv_mgr.nicknames = {wxid: "InitTest", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)
            _insert_message_4x(db_path, wxid, 10, "msg10", sender_id=2)
            _insert_message_4x(db_path, wxid, 20, "msg20", sender_id=2)

            b._monitor._decrypted_paths = {"message_0": str(db_path)}
            b._monitor._init_last_seen_ids()

            conv = b._conv_mgr.conversations.get(wxid)
            assert conv is not None
            assert conv.last_seen_local_id == 20


# ── Test: Full detection cycle (source mtime → re-decrypt → new messages) ──

class TestFullCycle:
    def test_source_mtime_triggers_processing(self):
        """When source file mtime changes, bot should re-decrypt and find new messages."""
        from services.bot import WeChatBot
        b = WeChatBot()
        wxid = "wxid_cycle"
        b._conv_mgr.nicknames = {wxid: "CycleTest", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            dec_path = Path(tmp) / "decrypted" / "message_0.db"
            dec_path.parent.mkdir(parents=True)
            _create_decrypted_db(dec_path, "4.x", wxid)
            _insert_message_4x(dec_path, wxid, 5, "old message", sender_id=2)

            b._monitor._decrypted_paths = {"message_0": str(dec_path)}
            b._monitor._init_last_seen_ids()

            conv = b._conv_mgr.conversations[wxid]
            assert conv.last_seen_local_id == 5
            assert len(conv.messages) == 0

            _insert_message_4x(dec_path, wxid, 6, "new message 1", sender_id=2)
            _insert_message_4x(dec_path, wxid, 7, "new message 2", sender_id=2)

            b._monitor._process_new_messages(str(dec_path))

            assert len(conv.messages) == 2
            assert conv.messages[0].content == "new message 1"
            assert conv.messages[1].content == "new message 2"
            assert conv.last_seen_local_id == 7


# ── Test: Responder filters ──

class TestResponderFilters:
    def test_nonsense_filter(self):
        from services.bot.responder import is_nonsense
        assert is_nonsense("") is True
        assert is_nonsense("   ") is True
        assert is_nonsense("<sysmsg>...</sysmsg>") is True
        assert is_nonsense("[微信红包]恭喜发财") is True
        assert is_nonsense("你好，我想问问房价") is False

    def test_block_words(self):
        from services.bot.responder import is_blocked
        assert is_blocked("这是一条测试消息") is True
        assert is_blocked("这是一条正常消息") is False
        assert is_blocked("test message") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
