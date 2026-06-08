"""线索情报 API"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.leads.risk_engine import get_risk_leads, update_all_risks
from services.leads.action_extractor import get_today_actions, extract_actions_from_leads
from services.leads.briefing import generate_briefing
from services.leads.stats import get_stats
from services.db import (
    update_action, get_customers_by_category,
    get_group_stats, create_group, delete_group, set_customer_group,
)

router = APIRouter()


@router.get("/risk")
def leads_risk():
    leads = get_risk_leads()
    summary = {"high": 0, "medium": 0, "low": 0}
    for l in leads:
        summary[l["risk_level"]] = summary.get(l["risk_level"], 0) + 1
    # 自动提取待办
    extract_actions_from_leads(leads)
    return {"leads": leads, "summary": summary}


@router.get("/actions")
def leads_actions():
    return {"actions": get_today_actions()}


@router.post("/actions/{action_id}/done")
def action_done(action_id: int):
    ok = update_action(action_id, "done")
    return {"ok": ok}


@router.post("/actions/{action_id}/skip")
def action_skip(action_id: int):
    ok = update_action(action_id, "skipped")
    return {"ok": ok}


@router.get("/briefing")
def leads_briefing():
    return generate_briefing()


@router.get("/stats")
def leads_stats():
    return get_stats()


@router.post("/refresh")
def refresh_risks():
    summary = update_all_risks()
    leads = get_risk_leads()
    extract_actions_from_leads(leads)
    return {"ok": True, "summary": summary}


# ── 明细页 & 分组 & AI 话术 ──


@router.get("/customers")
def list_customers(cat: str = Query("active", description="分类: active|pending|silent|messages")):
    """按分类返回客户列表，用于明细页"""
    customers = get_customers_by_category(cat)
    # 补充前端需要的展示字段
    result = []
    for c in customers:
        profile = {}
        try:
            import json
            profile = json.loads(c.get("profile_json") or "{}")
        except Exception:
            pass

        import time as _time
        silence_days = 0
        if c.get("last_message_at"):
            silence_days = int((_time.time() - c["last_message_at"]) / 86400)

        # 生成标签
        tags = _build_tags(c, profile, silence_days)

        # 摘要：优先用 action 的 ai_suggestion，否则用画像摘要
        summary = profile.get("profiling_summary") or c.get("remark") or ""

        last_active = _time_ago(c.get("last_message_at"))

        result.append({
            "wxid": c["wxid"],
            "name": c.get("remark") or c.get("nickname") or c.get("alias") or c["wxid"],
            "group": c.get("group_id") or _stage_to_group(c.get("stage", "initial")),
            "group_id": c.get("group_id"),
            "messages": c.get("message_count", 0),
            "lastActive": last_active,
            "tags": tags,
            "summary": summary,
            "risk": c.get("risk_level", "low"),
            "stage": c.get("stage", "initial"),
            "silence_days": silence_days,
        })

    return {"cat": cat, "customers": result}


@router.get("/groups")
def list_groups():
    """返回所有分组 + 人数统计"""
    return {"groups": get_group_stats()}


class CreateGroupRequest(BaseModel):
    name: str
    color: str = "#6b7280"


@router.post("/groups")
def api_create_group(req: CreateGroupRequest):
    """创建自定义分组"""
    if not req.name.strip():
        return {"error": "分组名称不能为空"}
    return create_group(req.name.strip(), req.color)


@router.delete("/groups/{group_id}")
def api_delete_group(group_id: str):
    """删除自定义分组"""
    ok = delete_group(group_id)
    if not ok:
        return {"error": "系统分组不可删除"}
    return {"ok": True}


class SetGroupRequest(BaseModel):
    group_id: str | None = None


@router.patch("/customers/{wxid}/group")
def api_set_customer_group(wxid: str, req: SetGroupRequest):
    """设置客户的分组。group_id=null 回到 AI 自动分组。"""
    ok = set_customer_group(wxid, req.group_id)
    if not ok:
        return {"error": "客户或分组不存在"}
    return {"ok": True}


@router.post("/actions/{action_id}/generate-reply")
def generate_reply(action_id: int, force: bool = False):
    """AI 生成行动项对应的回复话术（已生成则返回缓存，force=True 强制重新生成）"""
    from services.leads.reply_generator import generate_reply as _gen
    result = _gen(action_id, force=force)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(404, result["error"])
    return result


# ── Helpers ──


def _stage_to_group(stage: str) -> str:
    """将 stage 映射为前端 group id"""
    mapping = {
        "initial": "ungrouped",
        "intent": "high_intent",
        "showing": "showing",
        "closed": "closed",
    }
    return mapping.get(stage, "ungrouped")


def _build_tags(customer: dict, profile: dict, silence_days: int) -> list[str]:
    """根据画像和状态生成标签"""
    tags = []
    stage = customer.get("stage", "initial")
    if stage == "intent":
        tags.append("高意向")
    elif stage == "showing":
        tags.append("带看中")
    elif stage == "closed":
        tags.append("已成交")
    elif customer.get("message_count", 0) <= 3:
        tags.append("新线索")

    if profile.get("budget_total_wan"):
        tags.append(f"预算 {profile['budget_total_wan']}万")
    if profile.get("preferred_area"):
        tags.append(profile["preferred_area"])
    if profile.get("purchase_purpose"):
        tags.append(profile["purchase_purpose"])

    if silence_days > 14:
        tags.append(f"{silence_days}天未联系")
    elif silence_days > 7:
        tags.append("沉默预警")

    return tags or ["未分组"]


def _time_ago(ts: float | None) -> str:
    """将 timestamp 转为友好的相对时间"""
    if not ts:
        return "未知"
    import time as _time
    diff = _time.time() - ts
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff / 60)}分钟前"
    if diff < 86400:
        return f"{int(diff / 3600)}小时前"
    if diff < 7 * 86400:
        return f"{int(diff / 86400)}天前"
    return f"{int(diff / 86400)}天前"
