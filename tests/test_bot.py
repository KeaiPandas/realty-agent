"""Offline tests for the WeChat bot and extraction helpers."""

import asyncio
import hashlib
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest


def _create_decrypted_db(path: Path, table_type: str = "4.x", wxid: str = "test_user"):
    conn = sqlite3.connect(str(path))
    if table_type == "4.x":
        table_hash = hashlib.md5(wxid.encode()).hexdigest()
        conn.execute(
            f"""
            CREATE TABLE Msg_{table_hash} (
                local_id INTEGER PRIMARY KEY,
                create_time REAL,
                local_type INTEGER,
                message_content TEXT,
                real_sender_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE Name2Id (
                rowid INTEGER PRIMARY KEY,
                user_name TEXT,
                is_session INTEGER
            )
            """
        )
        conn.execute("INSERT INTO Name2Id VALUES (1, 'self_wxid', 0)")
        conn.execute(f"INSERT INTO Name2Id VALUES (2, '{wxid}', 1)")
    else:
        conn.execute(
            """
            CREATE TABLE MSG (
                localId INTEGER PRIMARY KEY,
                StrTalker TEXT,
                CreateTime REAL,
                Type INTEGER,
                StrContent TEXT
            )
            """
        )
    conn.commit()
    conn.close()


def _insert_message_4x(
    path: Path,
    wxid: str,
    local_id: int,
    content: str,
    create_time: float | None = None,
    sender_id: int = 2,
):
    table_hash = hashlib.md5(wxid.encode()).hexdigest()
    conn = sqlite3.connect(str(path))
    conn.execute(
        f"INSERT INTO Msg_{table_hash} (local_id, create_time, local_type, message_content, real_sender_id) "
        f"VALUES (?, ?, 1, ?, ?)",
        (local_id, create_time or time.time(), content, sender_id),
    )
    conn.commit()
    conn.close()


def _insert_message_3x(
    path: Path,
    wxid: str,
    local_id: int,
    content: str,
    create_time: float | None = None,
):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO MSG (localId, StrTalker, CreateTime, Type, StrContent) VALUES (?, ?, ?, 1, ?)",
        (local_id, wxid, create_time or time.time(), content),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _stub_generate_reply(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "BOT_REPLY_DEBOUNCE_SECONDS", 0.01, raising=False)
    monkeypatch.setattr("services.bot.generate_reply", lambda conv, mgr: "mocked reply")


class DummyTransport:
    def __init__(self, outcome=None, exc=None):
        self.sent = []
        self.outcome = outcome
        self.exc = exc

    def send(
        self,
        wxid: str,
        text: str,
        nickname: str = "",
        guard_manual_conflict: bool = True,
        search_terms=None,
    ):
        from services.bot.sender import SendOutcome

        self.sent.append(
            {
                "wxid": wxid,
                "text": text,
                "nickname": nickname,
                "guard_manual_conflict": guard_manual_conflict,
            }
        )
        if self.exc:
            raise self.exc
        return self.outcome or SendOutcome(status="sent")


class DelayedTransport(DummyTransport):
    def __init__(self, delay: float = 0.05, outcome=None, exc=None):
        super().__init__(outcome=outcome, exc=exc)
        self.delay = delay

    def send(
        self,
        wxid: str,
        text: str,
        nickname: str = "",
        guard_manual_conflict: bool = True,
        search_terms=None,
    ):
        time.sleep(self.delay)
        return super().send(wxid, text, nickname, guard_manual_conflict, search_terms)


class TestConversation:
    def test_get_or_create_conv(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        bot._conv_mgr.nicknames = {"wxid_abc": "Alice"}
        conv = bot._conv_mgr.get_or_create("wxid_abc")
        assert conv.wxid == "wxid_abc"
        assert conv.nickname == "Alice"

    def test_profiles_prefer_alias_and_remark_for_search(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        bot._conv_mgr.profiles = {
            "wty512": {
                "nickname": "三文鱼泡饭",
                "alias": "acloudycloud",
                "remark": "宝",
            }
        }

        conv = bot._conv_mgr.get_or_create("wty512")
        assert conv.nickname == "宝"
        assert conv.search_terms == ["acloudycloud", "宝", "三文鱼泡饭", "wty512"]

    def test_get_conv_by_table(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        wxid = "wxid_test123"
        bot._conv_mgr.nicknames = {wxid: "TestUser"}
        table_name = f"Msg_{hashlib.md5(wxid.encode()).hexdigest()}"
        conv = bot._conv_mgr.get_by_table(table_name)
        assert conv is not None
        assert conv.wxid == wxid


class TestMessageProcessing:
    def test_process_4x_messages(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        wxid = "wxid_customer1"
        bot._conv_mgr.nicknames = {wxid: "Customer1", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)

            conv = bot._conv_mgr.get_or_create(wxid)
            _insert_message_4x(db_path, wxid, 1, "hello", sender_id=2)
            _insert_message_4x(db_path, wxid, 2, "need a house", sender_id=2)

            bot._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 2
            assert conv.messages[0].content == "hello"
            assert conv.messages[1].content == "need a house"
            assert conv.last_seen_local_id == 2

    def test_process_3x_messages(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        wxid = "wxid_old_customer"
        bot._conv_mgr.nicknames = {wxid: "OldCustomer"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ChatMsg.db"
            _create_decrypted_db(db_path, "3.x")
            _insert_message_3x(db_path, wxid, 1, "hello")

            conv = bot._conv_mgr.get_or_create(wxid)
            bot._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 1
            assert conv.messages[0].content == "hello"

    def test_only_new_messages_processed(self):
        from services.bot import WeChatBot

        bot = WeChatBot(transport=DummyTransport())
        wxid = "wxid_test"
        bot._conv_mgr.nicknames = {wxid: "Test", "self_wxid": "Me"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            _create_decrypted_db(db_path, "4.x", wxid)
            _insert_message_4x(db_path, wxid, 1, "old msg", sender_id=2)
            _insert_message_4x(db_path, wxid, 2, "new msg", sender_id=2)

            conv = bot._conv_mgr.get_or_create(wxid)
            conv.last_seen_local_id = 1
            bot._monitor._process_new_messages(str(db_path))

            assert len(conv.messages) == 1
            assert conv.messages[0].content == "new msg"
            assert conv.last_seen_local_id == 2


class TestAutoSend:
    def test_auto_mode_sends_on_running_loop(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DummyTransport()
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_contact_settings("wxid_auto", mode="auto")

            conv = bot._conv_mgr.get_or_create("wxid_auto")
            msg = BotMessage(
                id="1",
                wxid="wxid_auto",
                content="hi",
                is_from_customer=True,
                timestamp="2026-05-22 00:00",
            )

            bot._on_customer_message(conv, msg)
            await asyncio.sleep(0.1)

            assert transport.sent == [
                {
                    "wxid": "wxid_auto",
                    "text": "mocked reply",
                    "nickname": "wxid_auto",
                    "guard_manual_conflict": True,
                }
            ]
            assert msg.reply_status == "sent"
            assert conv.pending_reply is None

            await bot.stop()

        asyncio.run(scenario())

    def test_global_takeover_applies_without_per_contact_override(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DummyTransport()
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="auto", enabled=True)

            conv = bot._conv_mgr.get_or_create("wxid_global")
            msg = BotMessage(
                id="2",
                wxid="wxid_global",
                content="hello from customer",
                is_from_customer=True,
                timestamp="2026-05-23 00:00",
            )

            bot._on_customer_message(conv, msg)
            await asyncio.sleep(0.1)

            assert transport.sent == [
                {
                    "wxid": "wxid_global",
                    "text": "mocked reply",
                    "nickname": "wxid_global",
                    "guard_manual_conflict": True,
                }
            ]
            assert msg.reply_status == "sent"
            conversations = bot.get_conversations()
            assert conversations[0]["effective_mode"] == "auto"
            assert conversations[0]["mode_source"] == "global"
            await bot.stop()

        asyncio.run(scenario())

    def test_quick_customer_burst_is_debounced_to_single_reply(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DummyTransport()
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_contact_settings("wxid_burst", mode="auto")

            conv = bot._conv_mgr.get_or_create("wxid_burst")
            msg1 = BotMessage(
                id="burst-1",
                wxid="wxid_burst",
                content="在吗",
                is_from_customer=True,
                timestamp="2026-05-24 20:00",
            )
            conv.messages.append(msg1)
            bot._on_customer_message(conv, msg1)

            await asyncio.sleep(0.003)

            msg2 = BotMessage(
                id="burst-2",
                wxid="wxid_burst",
                content="我想咨询一下房子",
                is_from_customer=True,
                timestamp="2026-05-24 20:00",
            )
            conv.messages.append(msg2)
            bot._on_customer_message(conv, msg2)

            await asyncio.sleep(0.08)

            assert len(transport.sent) == 1
            assert transport.sent[0]["wxid"] == "wxid_burst"
            assert msg1.reply_status == ""
            assert msg2.reply_status == "sent"
            assert conv.pending_reply is None

            await bot.stop()

        asyncio.run(scenario())

    def test_contact_disabled_overrides_global_auto(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DummyTransport()
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="auto", enabled=True)
            bot.update_contact_settings("wxid_disabled", mode="semi_auto", enabled=False)

            conv = bot._conv_mgr.get_or_create("wxid_disabled")
            msg = BotMessage(
                id="3",
                wxid="wxid_disabled",
                content="still there?",
                is_from_customer=True,
                timestamp="2026-05-23 01:00",
            )

            bot._on_customer_message(conv, msg)
            await asyncio.sleep(0.05)

            assert transport.sent == []
            assert conv.pending_reply is None
            assert msg.reply_status == ""

            conversations = bot.get_conversations()
            assert conversations[0]["effective_mode"] == "disabled"
            assert conversations[0]["mode_source"] == "contact"
            await bot.stop()

        asyncio.run(scenario())

    def test_manual_conflict_deferred_to_pending(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage
        from services.bot.sender import MANUAL_CONFLICT, SendOutcome

        async def scenario():
            transport = DummyTransport(
                outcome=SendOutcome(
                    status="deferred",
                    reason=MANUAL_CONFLICT,
                    detail="manual activity detected",
                )
            )
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="auto", enabled=True)

            conv = bot._conv_mgr.get_or_create("wxid_conflict")
            msg = BotMessage(
                id="4",
                wxid="wxid_conflict",
                content="quote please",
                is_from_customer=True,
                timestamp="2026-05-23 02:00",
            )

            bot._on_customer_message(conv, msg)
            await asyncio.sleep(0.1)

            assert len(transport.sent) == 1
            assert msg.reply_status == "pending"
            assert msg.reply_status_reason == MANUAL_CONFLICT
            assert conv.pending_reply is msg

            pending = bot.get_pending("wxid_conflict")
            assert pending["reason"] == MANUAL_CONFLICT
            await bot.stop()

        asyncio.run(scenario())

    @pytest.mark.parametrize(
        ("reason", "detail"),
        [
            ("focus_failed", "Unable to focus WeChat"),
            ("send_failed", "Message editor was not cleared after send"),
        ],
    )
    def test_send_failures_fall_back_to_pending(self, reason, detail):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage
        from services.bot.sender import SenderFailure

        async def scenario():
            transport = DummyTransport(exc=SenderFailure(reason, detail))
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="auto", enabled=True)

            conv = bot._conv_mgr.get_or_create(f"wxid_{reason}")
            msg = BotMessage(
                id=f"msg-{reason}",
                wxid=conv.wxid,
                content="hello",
                is_from_customer=True,
                timestamp="2026-05-23 03:00",
            )

            bot._on_customer_message(conv, msg)
            await asyncio.sleep(0.1)

            assert len(transport.sent) == 1
            assert msg.reply_status == "pending"
            assert msg.reply_status_reason == reason
            assert conv.pending_reply is msg

            conversations = bot.get_conversations()
            assert conversations[0]["pending_reply"]["reason"] == reason
            await bot.stop()

        asyncio.run(scenario())

    def test_approve_reply_does_not_clear_newer_pending_message(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DelayedTransport(delay=0.08)
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="semi_auto", enabled=True)

            conv = bot._conv_mgr.get_or_create("wxid_race")
            msg1 = BotMessage(
                id="100",
                wxid="wxid_race",
                content="first",
                is_from_customer=True,
                timestamp="2026-05-23 04:00",
            )
            bot._on_customer_message(conv, msg1)

            approve_task = asyncio.create_task(bot.approve_reply("wxid_race"))
            await asyncio.sleep(0.02)

            msg2 = BotMessage(
                id="101",
                wxid="wxid_race",
                content="second",
                is_from_customer=True,
                timestamp="2026-05-23 04:01",
            )
            bot._on_customer_message(conv, msg2)
            await approve_task

            assert msg1.reply_status == "sent"
            assert conv.pending_reply is msg2
            assert msg2.reply_status == "pending"

            await bot.stop()

        asyncio.run(scenario())

    def test_approve_waits_for_scheduled_generation(self):
        from services.bot import WeChatBot
        from services.bot.models import BotMessage

        async def scenario():
            transport = DummyTransport()
            bot = WeChatBot(transport=transport)
            await bot.start()
            bot.update_global_settings(mode="semi_auto", enabled=True)

            conv = bot._conv_mgr.get_or_create("wxid_wait")
            msg = BotMessage(
                id="wait-1",
                wxid="wxid_wait",
                content="hello",
                is_from_customer=True,
                timestamp="2026-05-24 20:01",
            )
            conv.messages.append(msg)
            bot._on_customer_message(conv, msg)

            result = await bot.approve_reply("wxid_wait")

            assert result is not None
            assert result["status"] == "sent"
            assert len(transport.sent) == 1
            assert msg.reply_status == "sent"

            await bot.stop()

        asyncio.run(scenario())


class TestSenderHelpers:
    def test_transport_falls_back_after_preferred_backend_failure(self):
        from services.bot.sender import PywinautoTransport
        from services.bot.wechat_backends import BackendError, ChatSessionBackend

        class FailingBackend(ChatSessionBackend):
            transport_mode = "desktop_rpa/wxauto"

            def has_manual_conflict(self):
                return False

            def send_text(self, target, text: str):
                raise BackendError("focus_failed", "wxauto failed")

        class SuccessBackend(ChatSessionBackend):
            transport_mode = "desktop_rpa/main_window"

            def __init__(self):
                self.sent = []

            def has_manual_conflict(self):
                return False

            def send_text(self, target, text: str):
                self.sent.append((target.wxid, text))

        transport = PywinautoTransport(backend=FailingBackend())
        fallback = SuccessBackend()
        transport._fallback_backend = fallback
        result = transport.send("filehelper", "hello", nickname="文件传输助手", guard_manual_conflict=False)

        assert result.status == "sent"
        assert fallback.sent == [("filehelper", "hello")]

    def test_split_message_preserves_content(self):
        from services.bot.wechat_backends import WindowsMainWindowBackend

        class FakeRandom:
            def randint(self, _minimum, _maximum):
                return 3

            def uniform(self, minimum, maximum):
                return minimum

        backend = WindowsMainWindowBackend()
        backend._rng = FakeRandom()

        text = "Hello there, thanks for reaching out. We have two listings that may fit. What is your budget?"
        segments = backend._split_message(text)

        assert "".join(segments) == text
        assert len(segments) >= 2

    def test_sleep_between_uses_random_delay(self, monkeypatch):
        from services.bot.sender import PywinautoTransport

        observed = {}

        class FakeRandom:
            def uniform(self, minimum, maximum):
                observed["range"] = (minimum, maximum)
                return 0.25

        transport = PywinautoTransport()
        transport._rng = FakeRandom()
        monkeypatch.setattr(
            "services.bot.sender.time.sleep",
            lambda value: observed.setdefault("sleep", value),
        )

        transport._sleep_between(0.1, 0.5)

        assert observed["range"] == (0.1, 0.5)
        assert observed["sleep"] == 0.25

    def test_send_button_detection_uses_green_state(self, monkeypatch):
        from PIL import Image

        from services.bot.wechat_backends import WindowRef, WindowsMainWindowBackend

        backend = WindowsMainWindowBackend()
        window = WindowRef(
            handle=1,
            title="chat",
            class_name="Qt51514QWindowIcon",
            rect=(0, 0, 900, 700),
        )

        enabled = Image.new("RGB", (900, 700), (30, 30, 30))
        for x in range(780, 880):
            for y in range(630, 680):
                enabled.putpixel((x, y), (35, 190, 110))

        disabled = Image.new("RGB", (900, 700), (30, 30, 30))
        for x in range(780, 880):
            for y in range(630, 680):
                disabled.putpixel((x, y), (60, 60, 60))

        monkeypatch.setattr(backend, "_capture_window", lambda _: enabled)
        assert backend._send_button_enabled(window) is True

        monkeypatch.setattr(backend, "_capture_window", lambda _: disabled)
        assert backend._send_button_enabled(window) is False

    def test_find_chat_window_prefers_exact_title(self, monkeypatch):
        from services.bot.wechat_backends import WindowRef, WindowsMainWindowBackend

        backend = WindowsMainWindowBackend()
        windows = [
            WindowRef(10, "微信", "Qt51514QWindowIcon", (0, 0, 100, 100)),
            WindowRef(11, "Alice", "Qt51514QWindowIcon", (0, 0, 100, 100)),
            WindowRef(12, "Bob", "Qt51514QWindowIcon", (0, 0, 100, 100)),
        ]
        monkeypatch.setattr(backend, "_list_wechat_windows", lambda: windows)

        matched = backend._find_chat_window(["Alice"], exact_only=True)
        assert matched is not None
        assert matched.handle == 11

        fallback = backend._find_chat_window(["Carol"], exclude_handles={10})
        assert fallback is not None
        assert fallback.handle == 11

    def test_pick_main_window_prefers_signed_in_window_and_filters_login_popup(self):
        from services.bot.wechat_backends import WindowRef, WindowsMainWindowBackend

        backend = WindowsMainWindowBackend()
        windows = [
            WindowRef(10, "Weixin", "Qt51514QWindowIcon", (0, 0, 180, 220), visible=False),
            WindowRef(11, "寰俊", "Qt51514QWindowIcon", (0, 0, 1200, 900)),
            WindowRef(12, "Alice", "Qt51514QWindowIcon", (0, 0, 900, 700)),
        ]

        usable = [window for window in windows if backend._is_usable_window(window)]
        picked = backend._pick_main_window(usable)

        assert [window.handle for window in usable] == [11, 12]
        assert picked is not None
        assert picked.handle == 11

    def test_pick_main_window_prefers_visible_window_when_signed_in_main_is_hidden(self):
        from services.bot.wechat_backends import WindowRef, WindowsMainWindowBackend

        backend = WindowsMainWindowBackend()
        windows = [
            WindowRef(11, "寰俊", "Qt51514QWindowIcon", (0, 0, 1200, 900), visible=False),
            WindowRef(12, "Alice", "Qt51514QWindowIcon", (0, 0, 900, 700)),
        ]

        picked = backend._pick_main_window(windows)

        assert picked is not None
        assert picked.handle == 12

        windows[0].visible = True
        picked = backend._pick_main_window(windows)
        assert picked is not None
        assert picked.handle == 11

    def test_open_conversation_accepts_foreground_popup_after_recent_double_click(self, monkeypatch):
        from services.bot.wechat_backends import ChatTarget, WindowRef, WindowsMainWindowBackend

        backend = WindowsMainWindowBackend()
        main_window = WindowRef(10, "微信", "Qt51514QWindowIcon", (0, 0, 1000, 800))
        popup = WindowRef(22, "宝", "Qt51514QWindowIcon", (0, 0, 900, 700))
        events = {"recent_clicked": False}

        monkeypatch.setattr(backend, "_find_chat_window", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            backend,
            "_list_wechat_windows",
            lambda: [main_window, popup],
        )
        monkeypatch.setattr(
            backend,
            "_dismiss_auxiliary_windows",
            lambda *_args: None,
        )
        monkeypatch.setattr(
            backend,
            "_select_conversation_via_search",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            backend,
            "_open_recent_conversation",
            lambda *_args: events.__setitem__("recent_clicked", True),
        )
        monkeypatch.setattr(
            backend,
            "_foreground_chat_window",
            lambda *_args: popup if events["recent_clicked"] else None,
        )
        monkeypatch.setattr(backend, "_focus_window", lambda *_args: None)

        opened = backend._chat_with(
            main_window,
            mouse=None,
            keyboard=None,
            target=ChatTarget(wxid="wty512", search_terms=["wty512"]),
        )
        assert opened.handle == 22

    def test_chat_input_point_targets_right_side_editor(self):
        from services.bot.wechat_backends import WindowsMainWindowBackend

        point = WindowsMainWindowBackend._chat_input_point((609, 320, 1951, 1291))

        assert point[0] > 1000
        assert point[1] > 1100


class TestExtraction:
    def test_extract_limit_is_global(self):
        from services.sync.extract import extract_dm_messages

        with tempfile.TemporaryDirectory() as tmp:
            contact_db = Path(tmp) / "contact.db"
            c = sqlite3.connect(contact_db)
            c.execute("CREATE TABLE Contact (UserName TEXT, NickName TEXT, Alias TEXT, Remark TEXT)")
            c.execute("INSERT INTO Contact VALUES ('wxid_a', 'Alice', '', '')")
            c.commit()
            c.close()

            db_paths = {"contact": str(contact_db)}
            base_ts = time.time()
            for idx in range(2):
                msg_db = Path(tmp) / f"message_{idx}.db"
                _create_decrypted_db(msg_db, "4.x", "wxid_a")
                _insert_message_4x(msg_db, "wxid_a", 1, f"old-{idx}", create_time=base_ts + idx)
                _insert_message_4x(
                    msg_db,
                    "wxid_a",
                    2,
                    f"new-{idx}",
                    create_time=base_ts + 10 + idx,
                )
                db_paths[f"message_{idx}"] = str(msg_db)

            messages = extract_dm_messages(db_paths, "wxid_a", limit=2)
            assert len(messages) == 2
            assert [m["content"] for m in messages] == ["new-0", "new-1"]


class TestMonitor:
    def test_init_last_seen_ids_does_not_skip_unprocessed_existing_message(self):
        from services.bot.conversation import ConversationManager
        from services.bot.models import BotMessage
        from services.bot.monitor import Monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "message_0.db"
            wxid = "wty512"
            _create_decrypted_db(db_path, "4.x", wxid)
            _insert_message_4x(db_path, wxid, 17, "older msg", sender_id=2)
            _insert_message_4x(db_path, wxid, 18, "newer msg", sender_id=2)

            conv_mgr = ConversationManager()
            conv_mgr.nicknames = {wxid: "Test User"}
            conv = conv_mgr.get_or_create(wxid)
            conv.last_seen_local_id = 17
            conv.messages.append(
                BotMessage(
                    id="17",
                    wxid=wxid,
                    content="older msg",
                    is_from_customer=True,
                    timestamp="2026-05-24 15:27",
                )
            )

            monitor = Monitor(conv_mgr)
            monitor._decrypted_paths = {"message_0": str(db_path)}

            monitor._init_last_seen_ids()

            assert conv.last_seen_local_id == 17

    def test_wxauto_monitor_maps_session_name_back_to_known_contact(self):
        from services.bot.conversation import ConversationManager
        from services.bot.monitor import Monitor

        class FakeWxautoMessage:
            def __init__(self, content, message_id):
                self.type = "friend"
                self.content = content
                self.id = message_id
                self.sender = "宝"

        class FakeWxautoClient:
            def GetAllNewMessage(self, max_round=5):
                return {
                    "宝": [FakeWxautoMessage("我想了解一下版纳的房产", "msg-1")]
                }

        captured = []
        conv_mgr = ConversationManager()
        conv_mgr.profiles = {
            "wty512": {
                "nickname": "宝",
                "remark": "宝",
                "alias": "wty512",
                "search_terms": ["宝", "wty512"],
            }
        }
        monitor = Monitor(conv_mgr, on_customer_msg=lambda conv, msg: captured.append((conv, msg)))
        monitor._version = "3.x"
        monitor._wxauto_client = FakeWxautoClient()

        monitor._check_wxauto_messages()

        conv = conv_mgr.get("wty512")
        assert conv is not None
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "我想了解一下版纳的房产"
        assert captured
        assert captured[0][0].wxid == "wty512"


class TestScheduler:
    def test_scheduled_pipeline_runs_inside_existing_loop(self, monkeypatch):
        from api.scheduler import _run_scheduled_pipeline

        captured = {}

        async def fake_scheduled_async(req):
            captured["contact_id"] = req.contact_id
            captured["date_start"] = req.date_start
            captured["date_end"] = req.date_end

        monkeypatch.setattr("api.scheduler._scheduled_async", fake_scheduled_async)

        asyncio.run(_run_scheduled_pipeline({"contact_id": "wxid_sched", "scan_mode": "all"}))

        assert captured == {
            "contact_id": "wxid_sched",
            "date_start": None,
            "date_end": None,
        }


class TestProfileParser:
    def test_empty_profile_response_raises(self, monkeypatch):
        from agents import profile_parser

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            async def ainvoke(self, messages):
                class Response:
                    content = "{}"

                return Response()

        monkeypatch.setattr(profile_parser, "ChatOpenAI", FakeLLM)

        with pytest.raises(ValueError, match="empty customer profile"):
            asyncio.run(profile_parser.parse_chat_to_profile("test chat"))
