"""Bot data models."""
from __future__ import annotations

from config import settings


class BotContactSettings:
    def __init__(
        self,
        wxid: str,
        mode: str = "",
        enabled: bool = True,
        system_prompt_override: str = "",
    ):
        self.wxid = wxid
        self.mode = mode or settings.BOT_DEFAULT_MODE
        self.enabled = enabled
        self.system_prompt_override = system_prompt_override


class BotGlobalSettings:
    def __init__(self, mode: str = "", enabled: bool = False):
        self.mode = mode or settings.BOT_DEFAULT_MODE
        self.enabled = enabled


class BotMessage:
    def __init__(
        self,
        id: str,
        wxid: str,
        content: str,
        is_from_customer: bool,
        timestamp: str,
        reply: str = "",
        reply_status: str = "",
        reply_status_reason: str = "",
    ):
        self.id = id
        self.wxid = wxid
        self.content = content
        self.is_from_customer = is_from_customer
        self.timestamp = timestamp
        self.reply = reply
        self.reply_status = reply_status  # pending / sent / rejected
        self.reply_status_reason = reply_status_reason


class BotConversation:
    def __init__(
        self,
        wxid: str,
        nickname: str = "",
        alias: str = "",
        remark: str = "",
        search_terms: list[str] | None = None,
    ):
        self.wxid = wxid
        self.nickname = nickname
        self.alias = alias
        self.remark = remark
        self.search_terms = list(search_terms or [])
        self.messages: list[BotMessage] = []
        self.pending_reply: BotMessage | None = None
        self.last_seen_local_id: int = 0
