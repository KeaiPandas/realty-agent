"""Bot 消息发送 — pywinauto UI 自动化"""
from __future__ import annotations

import time

from services.bot.events import broadcast


class SenderTransport:
    """消息发送传输层接口"""

    def send(self, wxid: str, text: str):
        raise NotImplementedError


class PywinautoTransport(SenderTransport):
    """通过 pywinauto 自动化发送消息"""

    def send(self, wxid: str, text: str):
        from pywinauto import Application

        try:
            app = Application().connect(path="Weixin.exe")
        except Exception:
            raise RuntimeError("未找到微信窗口，请确保微信已登录")

        main_window = None
        for win in app.windows():
            if win.element_info.class_name == "WeChatMainWndForPC":
                main_window = win
                break
        if not main_window:
            try:
                main_window = app.top_window()
            except Exception:
                raise RuntimeError("无法获取微信主窗口")

        main_window.set_focus()

        import pywinauto.keyboard as kb
        kb.send_keys('^f')
        time.sleep(0.5)

        search_edit = None
        try:
            search_edit = main_window.child_window(
                auto_id="SearchLineEdit", control_type="Edit"
            )
        except Exception:
            pass

        if search_edit:
            search_edit.set_text(wxid)
        else:
            kb.send_keys(wxid)

        time.sleep(1)
        kb.send_keys('{ENTER}')
        time.sleep(0.5)

        msg_edit = None
        try:
            msg_edit = main_window.child_window(
                auto_id="ChatEditWndForPC", control_type="Edit"
            )
        except Exception:
            pass

        if msg_edit:
            msg_edit.set_text(text)
        else:
            kb.send_keys(text)

        time.sleep(0.3)
        kb.send_keys('{ENTER}')
        time.sleep(0.3)
        kb.send_keys('{ESC}')
