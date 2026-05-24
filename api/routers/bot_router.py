"""微信机器人 REST API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.bot import bot


router = APIRouter()


class ApproveRequest(BaseModel):
    edited_reply: str = ""


class SendRequest(BaseModel):
    wxid: str
    content: str


class ContactSettingsUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None


class GlobalSettingsUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None


@router.get("/status")
def get_status():
    return bot.get_status()


@router.post("/start")
async def start_bot():
    if bot.running:
        return {"status": "already_running"}
    await bot.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot():
    if not bot.running:
        return {"status": "already_stopped"}
    await bot.stop()
    return {"status": "stopped"}


@router.get("/conversations")
def get_conversations():
    return bot.get_conversations()


@router.get("/conversations/{wxid}/messages")
def get_messages(wxid: str, limit: int = 50):
    messages = bot.get_messages(wxid, limit)
    if not messages:
        raise HTTPException(404, "会话不存在")
    return messages


@router.post("/conversations/{wxid}/approve")
async def approve_reply(wxid: str, req: ApproveRequest):
    result = await bot.approve_reply(wxid, req.edited_reply)
    if not result:
        raise HTTPException(404, "没有待审批的回复")
    return result


@router.post("/conversations/{wxid}/reject")
def reject_reply(wxid: str):
    result = bot.reject_reply(wxid)
    if not result:
        raise HTTPException(404, "没有待审批的回复")
    return result


@router.get("/settings")
def get_settings():
    return bot.get_contact_settings_list()


@router.get("/settings/global")
def get_global_settings():
    return bot.get_global_settings()


@router.patch("/settings/global")
def update_global_settings(req: GlobalSettingsUpdate):
    return bot.update_global_settings(req.mode, req.enabled)


@router.patch("/settings/{wxid}")
def update_settings(wxid: str, req: ContactSettingsUpdate):
    return bot.update_contact_settings(wxid, req.mode, req.enabled)


@router.post("/send")
async def send_message(req: SendRequest):
    if not req.wxid or not req.content:
        raise HTTPException(400, "wxid 和 content 不能为空")
    return await bot.send_message_manual(req.wxid, req.content)
