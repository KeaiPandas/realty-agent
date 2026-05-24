"""Bot conversation and takeover settings management."""
import hashlib

from services.bot.models import BotContactSettings, BotConversation, BotGlobalSettings


class ConversationManager:
    def __init__(self):
        self._conversations: dict[str, BotConversation] = {}
        self._contact_settings: dict[str, BotContactSettings] = {}
        self._nicknames: dict[str, str] = {}
        self._profiles: dict[str, dict] = {}
        self._global_settings = BotGlobalSettings()

    @property
    def conversations(self) -> dict[str, BotConversation]:
        return self._conversations

    @property
    def nicknames(self) -> dict[str, str]:
        return self._nicknames

    @nicknames.setter
    def nicknames(self, value: dict[str, str]):
        self._nicknames = value
        for wxid, nickname in value.items():
            profile = self._profiles.get(wxid, {})
            profile["wxid"] = wxid
            profile["nickname"] = nickname
            profile.setdefault("alias", "")
            profile.setdefault("remark", "")
            profile["display_name"] = profile.get("remark") or nickname or wxid
            profile["search_terms"] = self._build_search_terms(
                profile.get("alias", ""),
                profile.get("remark", ""),
                nickname,
                wxid,
            )
            self._profiles[wxid] = profile
            if wxid in self._conversations:
                self._apply_profile(self._conversations[wxid], profile)

    @property
    def profiles(self) -> dict[str, dict]:
        return self._profiles

    @profiles.setter
    def profiles(self, value: dict[str, dict]):
        self._profiles = {}
        self._nicknames = {}
        for wxid, profile in value.items():
            normalized = {
                "wxid": wxid,
                "nickname": profile.get("nickname", ""),
                "alias": profile.get("alias", ""),
                "remark": profile.get("remark", ""),
            }
            normalized["display_name"] = (
                profile.get("display_name")
                or normalized["remark"]
                or normalized["nickname"]
                or normalized["alias"]
                or wxid
            )
            normalized["search_terms"] = self._build_search_terms(
                *(profile.get("search_terms") or []),
                normalized["alias"],
                normalized["remark"],
                normalized["nickname"],
                wxid,
            )
            self._profiles[wxid] = normalized
            self._nicknames[wxid] = normalized["display_name"]

        for wxid, conv in self._conversations.items():
            profile = self._profiles.get(wxid)
            if profile:
                self._apply_profile(conv, profile)

    def get_or_create(self, wxid: str) -> BotConversation:
        if wxid not in self._conversations:
            profile = self._profiles.get(wxid, {})
            self._conversations[wxid] = BotConversation(
                wxid=wxid,
                nickname=profile.get("display_name") or self._nicknames.get(wxid, wxid),
                alias=profile.get("alias", ""),
                remark=profile.get("remark", ""),
                search_terms=profile.get("search_terms") or self._build_search_terms(
                    self._nicknames.get(wxid, ""),
                    wxid,
                ),
            )
        return self._conversations[wxid]

    def get_by_table(self, table_name: str) -> BotConversation | None:
        table_hash = table_name[4:]
        for wxid in self._nicknames:
            if hashlib.md5(wxid.encode()).hexdigest() == table_hash:
                return self.get_or_create(wxid)
        return None

    def get(self, wxid: str) -> BotConversation | None:
        return self._conversations.get(wxid)

    def update_settings(
        self, wxid: str, mode: str | None = None, enabled: bool | None = None
    ) -> dict:
        cs = self._contact_settings.get(wxid)
        if not cs:
            cs = BotContactSettings(wxid)
            self._contact_settings[wxid] = cs
        if mode is not None:
            cs.mode = mode
        if enabled is not None:
            cs.enabled = enabled
        return {"wxid": cs.wxid, "mode": cs.mode, "enabled": cs.enabled}

    def update_global_settings(
        self, mode: str | None = None, enabled: bool | None = None
    ) -> dict:
        if mode is not None:
            self._global_settings.mode = mode
        if enabled is not None:
            self._global_settings.enabled = enabled
        return self.get_global_settings()

    def get_settings(self, wxid: str) -> BotContactSettings | None:
        return self._contact_settings.get(wxid)

    def get_effective_settings(self, wxid: str) -> dict:
        contact = self._contact_settings.get(wxid)
        if contact:
            return {
                "wxid": wxid,
                "mode": contact.mode,
                "enabled": contact.enabled,
                "source": "contact",
            }
        return {
            "wxid": wxid,
            "mode": self._global_settings.mode,
            "enabled": self._global_settings.enabled,
            "source": "global",
        }

    def get_settings_list(self) -> list[dict]:
        return [
            {"wxid": cs.wxid, "mode": cs.mode, "enabled": cs.enabled}
            for cs in self._contact_settings.values()
        ]

    def get_global_settings(self) -> dict:
        return {
            "mode": self._global_settings.mode,
            "enabled": self._global_settings.enabled,
        }

    def get_search_terms(self, wxid: str) -> list[str]:
        conv = self._conversations.get(wxid)
        if conv and conv.search_terms:
            return list(conv.search_terms)
        profile = self._profiles.get(wxid, {})
        return self._build_search_terms(
            *(profile.get("search_terms") or []),
            self._nicknames.get(wxid, ""),
            wxid,
        )

    @property
    def active_count(self) -> int:
        return len(self._conversations)

    @staticmethod
    def _build_search_terms(*values: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            term = (value or "").strip()
            if not term:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            terms.append(term)
        return terms

    def _apply_profile(self, conv: BotConversation, profile: dict):
        conv.nickname = profile.get("display_name") or conv.nickname or conv.wxid
        conv.alias = profile.get("alias", "")
        conv.remark = profile.get("remark", "")
        conv.search_terms = list(
            profile.get("search_terms")
            or self._build_search_terms(conv.alias, conv.remark, conv.nickname, conv.wxid)
        )
