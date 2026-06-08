"""Bot sender orchestration with pluggable WeChat automation backends."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from config import settings
from services.bot.wechat_backends import (
    FOCUS_FAILED,
    MANUAL_CONFLICT,
    SEND_FAILED,
    BackendError,
    ChatTarget,
    WindowRef,
    WindowsMainWindowBackend,
    build_chat_backend,
)


@dataclass
class SendOutcome:
    status: str
    reason: str = ""
    detail: str = ""


class SenderFailure(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class SenderTransport:
    """Message transport abstraction."""

    transport_mode = "desktop_rpa"

    def send(
        self,
        wxid: str,
        text: str,
        nickname: str = "",
        guard_manual_conflict: bool = True,
        search_terms: list[str] | None = None,
    ) -> SendOutcome:
        raise NotImplementedError


class PywinautoTransport(SenderTransport):
    """Transport that delegates to the configured WeChat backend."""

    def __init__(self, backend=None):
        self._backend = backend
        self._rng = random.Random()
        self.transport_mode = "desktop_rpa/main_window"

    def send(
        self,
        wxid: str,
        text: str,
        nickname: str = "",
        guard_manual_conflict: bool = True,
        search_terms: list[str] | None = None,
    ) -> SendOutcome:
        target = ChatTarget(
            wxid=wxid,
            nickname=nickname,
            search_terms=self._build_search_terms(search_terms or [], nickname, wxid),
        )
        if not target.search_terms:
            raise SenderFailure(FOCUS_FAILED, "Missing contact identifier")

        backend = self._get_backend()

        if (
            guard_manual_conflict
            and settings.BOT_MANUAL_CONFLICT_GUARD
            and backend.has_manual_conflict()
        ):
            return SendOutcome(
                status="deferred",
                reason=MANUAL_CONFLICT,
                detail="Detected manual activity in WeChat window",
            )

        self._sleep_between(settings.BOT_THINK_DELAY_MIN, settings.BOT_THINK_DELAY_MAX)

        try:
            backend.send_text(target, text)
            return SendOutcome(status="sent")
        except BackendError as exc:
            raise SenderFailure(exc.reason, exc.detail) from exc
        except Exception as exc:
            raise SenderFailure(SEND_FAILED, str(exc)) from exc

    def _get_backend(self) -> WindowsMainWindowBackend:
        if self._backend is None:
            self._backend = build_chat_backend(settings.BOT_TRANSPORT_BACKEND)
        return self._backend

    @staticmethod
    def _build_search_terms(
        search_terms: list[str],
        nickname: str,
        wxid: str,
    ) -> list[str]:
        ordered = []
        seen: set[str] = set()
        for term in [*(search_terms or []), nickname, wxid]:
            value = (term or "").strip()
            if not value:
                continue
            # 排除 wxid_ 开头的内部ID，微信搜索框用不了
            if value.startswith("wxid_"):
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(value)
        return ordered

    def _sleep_between(self, minimum: float, maximum: float):
        if maximum <= 0:
            return
        floor = max(0.0, minimum)
        ceiling = max(floor, maximum)
        time.sleep(self._rng.uniform(floor, ceiling))
