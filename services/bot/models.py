"""Bot 数据模型"""
from __future__ import annotations

from config import settings


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
