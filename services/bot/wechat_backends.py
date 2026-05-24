"""Pluggable WeChat automation backends.

This module keeps the Bot's business flow independent from any single
desktop automation implementation. The public contract is intentionally
small and mirrors the mature `ChatWith` + `SendMsg` style used by
existing WeChat automation projects.
"""

from __future__ import annotations

import ctypes
import importlib
import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import sys

import psutil
import win32api
import win32clipboard
import win32con
import win32gui
import win32process

from config import settings


MANUAL_CONFLICT = "manual_conflict"
FOCUS_FAILED = "focus_failed"
SEND_FAILED = "send_failed"

MAIN_WINDOW_TITLE = "微信"
WINDOW_CLASS_CANDIDATES = {"Qt51514QWindowIcon", "WeChatMainWndForPC"}
WINDOW_TITLE_EXCLUDE = {"", "Weixin", MAIN_WINDOW_TITLE}
MIN_WINDOW_WIDTH = 420
MIN_WINDOW_HEIGHT = 320


@dataclass
class ChatTarget:
    wxid: str
    nickname: str = ""
    search_terms: list[str] = field(default_factory=list)


@dataclass
class WindowRef:
    handle: int
    title: str
    class_name: str
    rect: tuple[int, int, int, int]
    visible: bool = True

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def area(self) -> int:
        return self.width * self.height


class BackendError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class ChatSessionBackend(ABC):
    transport_mode = "desktop_rpa"

    def has_manual_conflict(self) -> bool:
        return False

    @abstractmethod
    def send_text(self, target: ChatTarget, text: str):
        raise NotImplementedError


class WxautoBackend(ChatSessionBackend):
    """Optional adapter for wxauto-style desktop automation."""

    transport_mode = "desktop_rpa/wxauto"

    def __init__(self):
        self._module_name, self._module, self._client = self._build_client()

    def send_text(self, target: ChatTarget, text: str):
        if self._module_name == "wxauto":
            self._send_text_legacy(target, text)
            return
        last_error = None
        for term in target.search_terms or [target.nickname, target.wxid]:
            if not term:
                continue
            try:
                self._client.ChatWith(term)
                try:
                    self._client.SendMsg(text)
                except TypeError:
                    self._client.SendMsg(text, who=term)
                return
            except Exception as exc:
                last_error = exc
                continue
        raise BackendError(FOCUS_FAILED, f"wxauto failed to open chat: {last_error or 'no target matched'}")

    def _send_text_legacy(self, target: ChatTarget, text: str):
        set_clipboard_text = getattr(self._module, "SetClipboardText", None)
        if set_clipboard_text is None:
            raise BackendError(SEND_FAILED, "wxauto missing SetClipboardText helper")

        last_error = None
        for term in target.search_terms or [target.nickname, target.wxid]:
            if not term:
                continue
            try:
                self._client.ChatWith(term)
                time.sleep(0.3)
                self._activate_client_foreground()
                editbox = self._client.ChatBox.EditControl()
                editbox.Click()
                time.sleep(0.2)
                set_clipboard_text(text)
                time.sleep(0.1)
                editbox.SendKeys("{Ctrl}v")
                time.sleep(0.1)
                if not self._legacy_editor_has_text(editbox):
                    editbox.Click()
                    time.sleep(0.15)
                    editbox.SendKeys("{Ctrl}v")
                    time.sleep(0.15)
                if not self._legacy_editor_has_text(editbox):
                    raise BackendError(SEND_FAILED, "wxauto editbox did not accept pasted text")
                editbox.SendKeys("{Enter}")
                return
            except Exception as exc:
                last_error = exc
                continue
        if isinstance(last_error, BackendError):
            raise last_error
        raise BackendError(FOCUS_FAILED, f"wxauto failed to open chat: {last_error or 'no target matched'}")

    @staticmethod
    def _legacy_editor_has_text(editbox) -> bool:
        try:
            value = editbox.GetValuePattern().Value
            return bool((value or "").strip())
        except Exception:
            return False

    def _activate_client_foreground(self):
        hwnd = getattr(self._client, "HWND", None)
        if not hwnd:
            raise BackendError(FOCUS_FAILED, "wxauto client has no main window handle")
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_SHOWWINDOW | win32con.SWP_NOSIZE | win32con.SWP_NOMOVE,
            )
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_SHOWWINDOW | win32con.SWP_NOSIZE | win32con.SWP_NOMOVE,
            )
            wechat_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
            current_tid = win32api.GetCurrentThreadId()
            attached = False
            try:
                attached = bool(win32process.AttachThreadInput(current_tid, wechat_tid, True))
            except Exception:
                attached = False
            try:
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetFocus(hwnd)
            finally:
                if attached:
                    try:
                        win32process.AttachThreadInput(current_tid, wechat_tid, False)
                    except Exception:
                        pass
        except Exception as exc:
            raise BackendError(FOCUS_FAILED, f"wxauto failed to activate WeChat: {exc}") from exc

    @staticmethod
    def _build_client():
        candidate_paths = [
            Path(__file__).resolve().parents[2] / "_vendor" / "wxauto4_src",
        ]
        for candidate_path in candidate_paths:
            if candidate_path.exists():
                path_str = str(candidate_path)
                if path_str not in sys.path:
                    sys.path.insert(0, path_str)

        if settings.WECHAT_VERSION == "3.x":
            candidates = ("wxauto", "wxauto4")
        else:
            candidates = ("wxauto4", "wxauto")
        errors: list[str] = []
        for module_name in candidates:
            try:
                module = importlib.import_module(module_name)
                client_cls = getattr(module, "WeChat", None)
                if client_cls is None:
                    errors.append(f"{module_name}: missing WeChat client")
                    continue
                if module_name == "wxauto":
                    return module_name, module, client_cls()
                hwnd = WxautoBackend._detect_main_hwnd()
                if hwnd:
                    return module_name, module, client_cls(hwnd=hwnd)
                return module_name, module, client_cls()
            except Exception as exc:
                errors.append(f"{module_name}: {exc}")
        raise RuntimeError(
            "wxauto backend unavailable: " + (" | ".join(errors) if errors else "missing WeChat client")
        )

    @staticmethod
    def _detect_main_hwnd() -> int | None:
        def is_main_window(window: tuple[int, str, str]) -> bool:
            hwnd, title, class_name = window
            return title == MAIN_WINDOW_TITLE and class_name in WINDOW_CLASS_CANDIDATES

        windows = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            if class_name not in WINDOW_CLASS_CANDIDATES:
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if psutil.Process(pid).name().lower() != "weixin.exe":
                    return
            except Exception:
                return
            windows.append((hwnd, title, class_name))

        win32gui.EnumWindows(callback, None)
        for hwnd, title, class_name in windows:
            if is_main_window((hwnd, title, class_name)):
                return hwnd
        return windows[0][0] if windows else None


class WindowsMainWindowBackend(ChatSessionBackend):
    """Native RPA backend that drives the WeChat main window directly."""

    transport_mode = "desktop_rpa/main_window"

    def __init__(self):
        self._last_bot_focus_at = 0.0
        self._rng = random.Random()

    def has_manual_conflict(self) -> bool:
        foreground = win32gui.GetForegroundWindow()
        if not foreground:
            return False
        if not self._is_wechat_handle(foreground):
            return False
        return (time.monotonic() - self._last_bot_focus_at) > 1.5

    def send_text(self, target: ChatTarget, text: str):
        from pywinauto import mouse
        import pywinauto.keyboard as keyboard

        if not target.search_terms:
            raise BackendError(FOCUS_FAILED, "Missing contact identifier")

        main_window = self._get_main_window()
        focus_retries = max(1, settings.BOT_FOCUS_RETRY_COUNT)
        send_retries = max(1, settings.BOT_SEND_RETRY_COUNT + 1)
        last_reason = FOCUS_FAILED
        last_error = "Unable to focus WeChat"

        for _ in range(focus_retries):
            try:
                self._focus_window(main_window)
                chat_window = self._chat_with(main_window, mouse, keyboard, target)
            except BackendError as exc:
                last_reason = exc.reason
                last_error = exc.detail
                main_window = self._get_main_window()
                continue

            for send_attempt in range(send_retries):
                try:
                    self._fill_editor(chat_window, mouse, keyboard, text)
                    self._confirm_editor_not_empty(chat_window)
                    keyboard.send_keys("{ENTER}")
                    self._confirm_send_complete(chat_window)
                    return
                except BackendError as exc:
                    last_reason = exc.reason
                    last_error = exc.detail
                    if send_attempt >= send_retries - 1:
                        break
                    self._sleep_between(0.3, 0.6)
                    chat_window = self._refresh_window(chat_window.handle)

        raise BackendError(last_reason, last_error)

    def _chat_with(
        self,
        main_window: WindowRef,
        mouse,
        keyboard,
        target: ChatTarget,
    ) -> WindowRef:
        existing = self._find_chat_window(target.search_terms, exact_only=True)
        if existing:
            self._focus_window(existing)
            return existing

        self._dismiss_auxiliary_windows(main_window.handle, keyboard)

        if self._select_conversation_via_search(main_window, mouse, keyboard, target):
            return self._refresh_window(main_window.handle)

        known_handles = {window.handle for window in self._list_wechat_windows()}
        self._open_recent_conversation(main_window, mouse)
        active_popup = self._foreground_chat_window(main_window.handle)
        if active_popup:
            self._focus_window(active_popup)
            return active_popup
        popup = self._wait_for_chat_window(target.search_terms, known_handles)
        if popup:
            self._focus_window(popup)
            return popup
        return self._refresh_window(main_window.handle)

    def _get_main_window(self) -> WindowRef:
        windows = self._list_wechat_windows()
        picked = self._pick_main_window(windows)
        if picked is not None:
            return picked
        raise BackendError(FOCUS_FAILED, "Failed to find WeChat main window")

    def _focus_window(self, window: WindowRef):
        last_detail = "Unable to focus WeChat window"
        deadline = time.monotonic() + 1.5
        try:
            while time.monotonic() < deadline:
                try:
                    self._force_foreground_window(window.handle)
                except Exception as exc:
                    last_detail = f"Force foreground failed: {exc}"
                try:
                    from pywinauto import Desktop

                    Desktop(backend="win32").window(handle=window.handle).set_focus()
                except Exception as exc:
                    last_detail = f"Desktop focus failed: {exc}"
                try:
                    win32gui.SetForegroundWindow(window.handle)
                except Exception as exc:
                    last_detail = f"Foreground focus failed: {exc}"
                    self._click_window_title(window)
                self._last_bot_focus_at = time.monotonic()
                self._sleep_between(0.1, 0.2)
                if self._is_foreground_window(window.handle):
                    return
                self._click_window_title(window)
                self._sleep_between(0.08, 0.15)
                if self._is_foreground_window(window.handle):
                    return
        except Exception as exc:
            raise BackendError(FOCUS_FAILED, f"Unable to focus WeChat window: {exc}") from exc
        raise BackendError(FOCUS_FAILED, last_detail)

    def _force_foreground_window(self, hwnd: int):
        if not self._is_window(hwnd):
            raise RuntimeError("window handle is invalid")

        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        foreground_tid = 0
        if foreground:
            foreground_tid, _ = win32process.GetWindowThreadProcessId(foreground)

        attached = False
        try:
            if foreground_tid and target_tid and foreground_tid != target_tid:
                attached = bool(user32.AttachThreadInput(foreground_tid, target_tid, True))

            user32.ShowWindow(hwnd, win32con.SW_RESTORE)
            user32.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            user32.SetWindowPos(
                hwnd,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
            self._last_bot_focus_at = time.monotonic()
        finally:
            if attached and foreground_tid and target_tid:
                user32.AttachThreadInput(foreground_tid, target_tid, False)

    def _click_window_title(self, window: WindowRef):
        from pywinauto import mouse

        left, top, right, _bottom = window.rect
        mouse.click(coords=(left + min(140, max(60, (right - left) // 6)), top + 18))

    def _dismiss_auxiliary_windows(self, main_handle: int, keyboard):
        for window in self._list_wechat_windows():
            if window.handle == main_handle or window.title in WINDOW_TITLE_EXCLUDE:
                continue
            try:
                self._focus_window(window)
                keyboard.send_keys("{ESC}")
                self._sleep_between(0.15, 0.3)
            except Exception:
                continue
        self._focus_window(self._refresh_window(main_handle))

    def _select_conversation_via_search(
        self,
        main_window: WindowRef,
        mouse,
        keyboard,
        target: ChatTarget,
    ) -> bool:
        for term in target.search_terms:
            self._focus_window(main_window)
            mouse.click(coords=self._search_box_point(main_window.rect))
            self._sleep_between(0.1, 0.2)
            keyboard.send_keys("^a{BACKSPACE}")
            self._sleep_between(0.1, 0.2)
            self._paste_text(term)
            keyboard.send_keys("^v")
            self._sleep_between(0.35, 0.55)
            mouse.click(coords=self._search_result_point(main_window.rect))
            self._last_bot_focus_at = time.monotonic()
            self._sleep_between(0.35, 0.55)
            keyboard.send_keys("{ESC}")
            self._sleep_between(0.1, 0.2)
            return True
        return False

    def _open_recent_conversation(self, main_window: WindowRef, mouse):
        mouse.click(coords=self._recent_item_point(main_window.rect))
        self._last_bot_focus_at = time.monotonic()
        self._sleep_between(0.35, 0.6)

    def _fill_editor(self, chat_window: WindowRef, mouse, keyboard, text: str):
        if not self._is_window(chat_window.handle):
            raise BackendError(FOCUS_FAILED, "Chat window is no longer available")

        self._focus_window(chat_window)
        mouse.click(coords=self._chat_input_point(chat_window.rect))
        self._sleep_between(0.15, 0.3)
        keyboard.send_keys("^a{BACKSPACE}")
        self._sleep_between(0.1, 0.2)

        segments = self._split_message(text)
        for index, segment in enumerate(segments):
            self._paste_text(segment)
            keyboard.send_keys("^v")
            if index < len(segments) - 1:
                self._sleep_between(
                    settings.BOT_SEGMENT_DELAY_MIN,
                    settings.BOT_SEGMENT_DELAY_MAX,
                )

    def _confirm_editor_not_empty(self, chat_window: WindowRef):
        if not self._wait_for_send_button_state(chat_window, expected_enabled=True, timeout=2.0):
            raise BackendError(SEND_FAILED, "Message editor remained empty after input")

    def _confirm_send_complete(self, chat_window: WindowRef):
        if not self._wait_for_send_button_state(chat_window, expected_enabled=False, timeout=3.0):
            raise BackendError(SEND_FAILED, "Message editor was not cleared after send")

    def _wait_for_send_button_state(
        self,
        chat_window: WindowRef,
        expected_enabled: bool,
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._send_button_enabled(chat_window) == expected_enabled:
                return True
            time.sleep(0.15)
        return self._send_button_enabled(chat_window) == expected_enabled

    def _send_button_enabled(self, chat_window: WindowRef) -> bool:
        image = self._capture_window(chat_window)
        width, height = image.size
        sample = image.crop(
            (
                max(0, width - 120),
                max(0, height - 70),
                max(1, width - 20),
                max(1, height - 20),
            )
        )
        if sample.width == 0 or sample.height == 0:
            return False
        pixels = sample.load()
        greenish = 0
        total = sample.width * sample.height
        for x in range(sample.width):
            for y in range(sample.height):
                red, green, blue = pixels[x, y][:3]
                if green > 120 and green > red + 25 and green > blue + 10:
                    greenish += 1
        return greenish >= max(40, total // 25)

    def _capture_window(self, chat_window: WindowRef):
        from PIL import ImageGrab

        left, top, right, bottom = chat_window.rect
        return ImageGrab.grab(bbox=(left, top, right, bottom))

    def _refresh_window(self, handle: int) -> WindowRef:
        if not self._is_window(handle):
            raise BackendError(FOCUS_FAILED, "Chat window is no longer available")
        return WindowRef(
            handle=handle,
            title=win32gui.GetWindowText(handle),
            class_name=win32gui.GetClassName(handle),
            rect=self._window_rect(handle),
            visible=bool(win32gui.IsWindowVisible(handle)),
        )

    def _wait_for_chat_window(
        self,
        search_terms: list[str],
        known_handles: set[int],
        timeout: float = 3.0,
    ) -> WindowRef | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            active_popup = self._foreground_chat_window()
            if active_popup and active_popup.handle not in known_handles:
                return active_popup
            popup = self._find_chat_window(search_terms, known_handles)
            if popup:
                return popup
            time.sleep(0.15)
        return self._find_chat_window(search_terms, known_handles)

    def _find_chat_window(
        self,
        search_terms: list[str],
        exclude_handles: set[int] | None = None,
        exact_only: bool = False,
    ) -> WindowRef | None:
        windows = self._list_wechat_windows()
        normalized_terms = {term.casefold() for term in search_terms if term}
        new_windows: list[WindowRef] = []
        fallback: list[WindowRef] = []

        for window in windows:
            if window.title in WINDOW_TITLE_EXCLUDE:
                continue
            if exclude_handles and window.handle in exclude_handles:
                continue
            fallback.append(window)
            if window.title.casefold() in normalized_terms:
                return window
            new_windows.append(window)

        if exact_only:
            return None
        if new_windows:
            return new_windows[0]
        if fallback:
            return fallback[0]
        return None

    def _list_wechat_windows(self) -> list[WindowRef]:
        windows: list[WindowRef] = []

        def callback(hwnd, _):
            if not self._is_wechat_handle(hwnd):
                return
            window = WindowRef(
                handle=hwnd,
                title=win32gui.GetWindowText(hwnd),
                class_name=win32gui.GetClassName(hwnd),
                rect=self._window_rect(hwnd),
                visible=bool(win32gui.IsWindowVisible(hwnd)),
            )
            if not self._is_usable_window(window):
                return
            windows.append(window)

        win32gui.EnumWindows(callback, None)
        windows.sort(key=self._window_sort_key)
        return windows

    def _is_wechat_handle(self, hwnd: int) -> bool:
        if not self._is_window(hwnd):
            return False
        if win32gui.GetClassName(hwnd) not in WINDOW_CLASS_CANDIDATES:
            return False
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name().lower() == "weixin.exe"
        except Exception:
            return False

    @staticmethod
    def _is_window(hwnd: int) -> bool:
        try:
            return bool(hwnd) and win32gui.IsWindow(hwnd)
        except Exception:
            return False

    def _foreground_chat_window(self, main_handle: int | None = None) -> WindowRef | None:
        hwnd = win32gui.GetForegroundWindow()
        if not self._is_wechat_handle(hwnd):
            return None
        title = win32gui.GetWindowText(hwnd)
        if title in WINDOW_TITLE_EXCLUDE:
            return None
        if main_handle and hwnd == main_handle:
            return None
        return self._refresh_window(hwnd)

    @staticmethod
    def _is_foreground_window(hwnd: int) -> bool:
        try:
            return bool(hwnd) and win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return False

    @staticmethod
    def _is_usable_window(window: WindowRef) -> bool:
        return window.width >= MIN_WINDOW_WIDTH and window.height >= MIN_WINDOW_HEIGHT

    @staticmethod
    def _window_sort_key(window: WindowRef) -> tuple[int, int, int, int]:
        return (window.title != MAIN_WINDOW_TITLE, not window.visible, -window.area, window.handle)

    def _pick_main_window(self, windows: list[WindowRef]) -> WindowRef | None:
        if not windows:
            return None
        ranked = sorted(windows, key=self._window_sort_key)
        return ranked[0]

    def _window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        try:
            from pywinauto import Desktop

            rect = Desktop(backend="win32").window(handle=hwnd).rectangle()
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return win32gui.GetWindowRect(hwnd)

    @staticmethod
    def _recent_item_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        return (
            left + max(155, int(width * 0.14)),
            top + max(125, int(height * 0.12)),
        )

    @staticmethod
    def _search_box_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        return (
            left + max(145, int(width * 0.12)),
            top + max(52, int(height * 0.04)),
        )

    @staticmethod
    def _search_result_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        return (
            left + max(130, int(width * 0.12)),
            top + max(145, int(height * 0.14)),
        )

    @staticmethod
    def _chat_input_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        return (
            left + max(460, int(width * 0.36)),
            bottom - max(118, int(height * 0.12)),
        )

    @staticmethod
    def _send_button_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
        left, top, right, bottom = rect
        width = right - left
        return (
            right - max(92, int(width * 0.07)),
            bottom - 34,
        )

    def _split_message(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return [""]
        count_min = max(1, settings.BOT_SEGMENT_COUNT_MIN)
        count_max = max(count_min, settings.BOT_SEGMENT_COUNT_MAX)
        segment_count = self._rng.randint(count_min, count_max)
        if segment_count <= 1 or len(text) < 8:
            return [text]

        boundaries: list[int] = []
        punct = "，。！？；\n,.!?; "
        preferred = [index + 1 for index, char in enumerate(text[:-1]) if char in punct]
        while preferred and len(boundaries) < segment_count - 1:
            next_boundary = preferred[len(preferred) // max(1, segment_count)]
            boundaries.append(next_boundary)
            preferred = [point for point in preferred if point > next_boundary]
        if len(boundaries) < segment_count - 1:
            approx = max(1, math.ceil(len(text) / segment_count))
            for idx in range(1, segment_count):
                cut = min(len(text) - 1, idx * approx)
                if cut not in boundaries:
                    boundaries.append(cut)
        boundaries = sorted(point for point in boundaries if 0 < point < len(text))

        segments = []
        start = 0
        for boundary in boundaries:
            segments.append(text[start:boundary])
            start = boundary
        segments.append(text[start:])
        return [segment for segment in segments if segment]

    @staticmethod
    def _paste_text(text: str):
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

    def _sleep_between(self, minimum: float, maximum: float):
        if maximum <= 0:
            return
        floor = max(0.0, minimum)
        ceiling = max(floor, maximum)
        time.sleep(self._rng.uniform(floor, ceiling))


class WxautoCompatibleBackend(WindowsMainWindowBackend):
    """Project-local backend inspired by wxauto's ChatWith + SendMsg flow."""

    transport_mode = "desktop_rpa/wxauto_compat"

    def send_text(self, target: ChatTarget, text: str):
        from pywinauto import mouse
        import pywinauto.keyboard as keyboard

        if not target.search_terms:
            raise BackendError(FOCUS_FAILED, "Missing contact identifier")

        main_window = self._get_main_window()
        chat_window = self.ChatWith(target, mouse=mouse, keyboard=keyboard, main_window=main_window)
        self.SendMsg(text, mouse=mouse, keyboard=keyboard, chat_window=chat_window)

    def ChatWith(
        self,
        target: ChatTarget,
        mouse,
        keyboard,
        main_window: WindowRef | None = None,
    ) -> WindowRef:
        main_window = main_window or self._get_main_window()
        return self._chat_with(main_window, mouse, keyboard, target)

    def SendMsg(
        self,
        text: str,
        mouse,
        keyboard,
        chat_window: WindowRef,
    ):
        if not self._is_window(chat_window.handle):
            raise BackendError(FOCUS_FAILED, "Chat window is no longer available")

        self._focus_window(chat_window)
        self._fill_editor_like_wxauto(chat_window, mouse, keyboard, text)
        self._confirm_editor_not_empty(chat_window)
        mouse.click(coords=self._send_button_point(chat_window.rect))
        self._sleep_between(0.15, 0.25)
        self._confirm_send_complete(chat_window)

    def _fill_editor_like_wxauto(self, chat_window: WindowRef, mouse, keyboard, text: str):
        self._focus_chat_input(chat_window, mouse)

        segments = self._split_message(text)
        for index, segment in enumerate(segments):
            self._ensure_chat_foreground(chat_window, mouse)
            self._paste_text(segment)
            keyboard.send_keys("^v")
            self._sleep_between(0.05, 0.12)
            if index < len(segments) - 1:
                self._sleep_between(
                    settings.BOT_SEGMENT_DELAY_MIN,
                    settings.BOT_SEGMENT_DELAY_MAX,
                )

        # wxauto retries clipboard paste aggressively when the editor stays empty.
        if not self._wait_for_send_button_state(chat_window, expected_enabled=True, timeout=0.6):
            self._ensure_chat_foreground(chat_window, mouse)
            self._paste_text(text)
            keyboard.send_keys("+{INSERT}")
            self._sleep_between(0.12, 0.2)

        if not self._wait_for_send_button_state(chat_window, expected_enabled=True, timeout=0.6):
            self._focus_chat_input(chat_window, mouse, double=True)
            self._paste_text(text)
            keyboard.send_keys("^v")

    def _ensure_chat_foreground(self, chat_window: WindowRef, mouse):
        if self._is_foreground_window(chat_window.handle):
            return
        refreshed = self._refresh_window(chat_window.handle)
        self._focus_window(refreshed)
        self._focus_chat_input(refreshed, mouse)

    def _focus_chat_input(self, chat_window: WindowRef, mouse, double: bool = False):
        point = self._chat_input_point(chat_window.rect)
        if double:
            mouse.double_click(coords=point)
        else:
            mouse.click(coords=point)
        self._sleep_between(0.15, 0.25)


def build_chat_backend(preferred: str | None = None) -> ChatSessionBackend:
    selected = (preferred or settings.BOT_TRANSPORT_BACKEND or "auto").strip().lower()
    if selected in {"wxauto", "wxauto4"}:
        return WxautoBackend()
    if selected in {"wxauto_compat", "compat"}:
        return WxautoCompatibleBackend()
    if selected in {"native", "main_window", "desktop_rpa"}:
        return WindowsMainWindowBackend()
    if selected == "auto":
        try:
            return WxautoBackend()
        except Exception:
            try:
                return WxautoCompatibleBackend()
            except Exception:
                return WindowsMainWindowBackend()
    raise RuntimeError(f"Unsupported bot transport backend: {selected}")
