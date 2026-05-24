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
    WxautoCompatibleBackend,
    WxautoBackend,
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
    """Legacy transport name kept for compatibility with the rest of the app."""

    def __init__(self, backend=None):
        self._backend = backend
        self._fallback_backend = None
        self._rng = random.Random()
        preferred = settings.BOT_TRANSPORT_BACKEND or "auto"
        self.transport_mode = f"desktop_rpa/{preferred}"

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

        if (
            guard_manual_conflict
            and settings.BOT_MANUAL_CONFLICT_GUARD
            and self._get_backend().has_manual_conflict()
        ):
            return SendOutcome(
                status="deferred",
                reason=MANUAL_CONFLICT,
                detail="Detected manual activity in WeChat window",
            )

        self._sleep_between(settings.BOT_THINK_DELAY_MIN, settings.BOT_THINK_DELAY_MAX)
        backend = self._get_backend()
        try:
            self.transport_mode = getattr(backend, "transport_mode", self.transport_mode)
            backend.send_text(target, text)
            return SendOutcome(status="sent")
        except BackendError as exc:
            fallback = self._get_fallback_backend(backend)
            if fallback is not None:
                try:
                    self.transport_mode = getattr(fallback, "transport_mode", self.transport_mode)
                    fallback.send_text(target, text)
                    return SendOutcome(status="sent")
                except BackendError as fallback_exc:
                    raise SenderFailure(fallback_exc.reason, fallback_exc.detail) from fallback_exc
            raise SenderFailure(exc.reason, exc.detail) from exc
        except Exception as exc:
            raise SenderFailure(SEND_FAILED, str(exc)) from exc

    def _get_backend(self):
        if self._backend is not None:
            return self._backend
        preferred = settings.BOT_TRANSPORT_BACKEND or "auto"
        try:
            self._backend = build_chat_backend(preferred)
        except Exception:
            if str(preferred).lower() not in {"native", "main_window", "desktop_rpa"}:
                self._backend = WindowsMainWindowBackend()
            else:
                raise
        return self._backend

    def _get_fallback_backend(self, current_backend):
        if isinstance(current_backend, WindowsMainWindowBackend):
            return None
        if isinstance(current_backend, WxautoCompatibleBackend):
            if self._fallback_backend is None:
                self._fallback_backend = WindowsMainWindowBackend()
            return self._fallback_backend
        if self._fallback_backend is None:
            self._fallback_backend = WxautoCompatibleBackend()
        return self._fallback_backend

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


__all__ = [
    "BackendError",
    "ChatTarget",
    "FOCUS_FAILED",
    "MANUAL_CONFLICT",
    "PywinautoTransport",
    "SEND_FAILED",
    "SendOutcome",
    "SenderFailure",
    "SenderTransport",
    "WindowRef",
    "WindowsMainWindowBackend",
    "WxautoCompatibleBackend",
    "WxautoBackend",
    "build_chat_backend",
]
