"""风险评分引擎 — 从客户数据计算流失风险"""
import json
import time

from services.db import get_conn


def calculate_risk(customer: dict) -> tuple[str, list[str]]:
    """计算单个客户的风险等级和原因

    Returns: (risk_level, reasons)
    """
    reasons = []
    now = time.time()

    last_msg = customer.get("last_message_at") or 0
    last_reply = customer.get("last_reply_at") or 0
    stage = customer.get("stage", "initial")
    profile_raw = customer.get("profile_json") or "{}"

    try:
        profile = json.loads(profile_raw) if isinstance(profile_raw, str) else profile_raw
    except (json.JSONDecodeError, TypeError):
        profile = {}

    silence_days = (now - last_msg) / 86400 if last_msg else 999
    unreplied = last_msg > last_reply and (now - last_msg) > 86400

    budget = profile.get("budget_total_wan")
    area = profile.get("preferred_area")
    next_followup = profile.get("next_followup_date")

    # 高风险条件
    if silence_days > 7 and (budget or area):
        reasons.append(f"沉默{int(silence_days)}天且有明确意向")
    if silence_days > 7 and stage in ("intent", "showing"):
        reasons.append(f"沉默{int(silence_days)}天，阶段={stage}")
    if next_followup:
        try:
            from datetime import datetime
            followup_ts = datetime.strptime(next_followup, "%Y-%m-%d").timestamp()
            if followup_ts < now - 86400:
                reasons.append(f"计划跟进日已过{next_followup}")
        except (ValueError, TypeError):
            pass
    if budget and stage in ("initial", "intent") and silence_days > 3:
        reasons.append(f"预算{budget}万未带看")

    if reasons:
        return "high", reasons

    # 中风险条件
    if silence_days > 3:
        reasons.append(f"沉默{int(silence_days)}天")
    if stage == "initial" and not last_reply:
        reasons.append("新线索未首次跟进")
    if unreplied:
        reasons.append("超过24h未回复")

    if reasons:
        return "medium", reasons

    return "low", []


def update_all_risks():
    """批量更新所有客户的风险评分"""
    from services.db import get_all_customers, upsert_customer

    customers = get_all_customers()
    summary = {"high": 0, "medium": 0, "low": 0}

    for c in customers:
        if not c.get("message_count", 0):
            continue  # 跳过无消息的客户

        level, reasons = calculate_risk(c)
        summary[level] += 1

        conn = get_conn()
        conn.execute(
            "UPDATE customers SET risk_level = ?, risk_updated_at = ? WHERE wxid = ?",
            (level, time.time(), c["wxid"]),
        )
        conn.commit()
        conn.close()

    return summary


def get_risk_leads() -> list[dict]:
    """获取按风险排序的客户列表（含原因和建议）"""
    update_all_risks()

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM customers WHERE message_count > 0 "
        "ORDER BY CASE risk_level "
        "WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "last_message_at DESC NULLS LAST"
    ).fetchall()
    conn.close()

    leads = []
    for r in rows:
        c = dict(r)
        level, reasons = calculate_risk(c)

        profile = {}
        try:
            profile = json.loads(c.get("profile_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        silence_days = 0
        if c.get("last_message_at"):
            silence_days = int((time.time() - c["last_message_at"]) / 86400)

        leads.append({
            "wxid": c["wxid"],
            "nickname": c.get("nickname") or c["wxid"],
            "stage": c.get("stage", "initial"),
            "risk_level": level,
            "risk_reasons": reasons,
            "last_message_time": c.get("last_message_at"),
            "silence_days": silence_days,
            "key_profile": {
                "budget": profile.get("budget_total_wan"),
                "area": profile.get("preferred_area"),
                "purpose": profile.get("purchase_purpose"),
                "payment": profile.get("payment_method"),
            },
            "message_count": c.get("message_count", 0),
        })

    return leads
