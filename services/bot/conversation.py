"""Bot 会话管理"""
import hashlib

from services.bot.models import BotConversation, BotContactSettings


class ConversationManager:
    def __init__(self):
        self._conversations: dict[str, BotConversation] = {}
        self._contact_settings: dict[str, BotContactSettings] = {}
        self._nicknames: dict[str, str] = {}

    @property
    def conversations(self) -> dict[str, BotConversation]:
        return self._conversations

    @property
    def nicknames(self) -> dict[str, str]:
        return self._nicknames

    @nicknames.setter
    def nicknames(self, value: dict[str, str]):
        self._nicknames = value

    def get_or_create(self, wxid: str) -> BotConversation:
        if wxid not in self._conversations:
            self._conversations[wxid] = BotConversation(
                wxid=wxid,
                nickname=self._nicknames.get(wxid, wxid),
            )
        return self._conversations[wxid]

    def get_by_table(self, table_name: str) -> BotConversation | None:
        """通过 4.x 的 Msg_<hash> 表名反查 wxid"""
        table_hash = table_name[4:]
        for wxid in self._nicknames:
            if hashlib.md5(wxid.encode()).hexdigest() == table_hash:
                return self.get_or_create(wxid)
        return None

    def get(self, wxid: str) -> BotConversation | None:
        return self._conversations.get(wxid)

    def update_settings(self, wxid: str, mode: str | None = None,
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

    def get_settings(self, wxid: str) -> BotContactSettings | None:
        return self._contact_settings.get(wxid)

    def get_settings_list(self) -> list[dict]:
        return [{
            "wxid": cs.wxid,
            "mode": cs.mode,
            "enabled": cs.enabled,
        } for cs in self._contact_settings.values()]

    @property
    def active_count(self) -> int:
        return len(self._conversations)
