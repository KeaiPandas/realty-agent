"""待办提取 — 从消息和画像自动生成行动项"""
import time

from services.db import create_action, get_pending_actions, get_conn


def extract_actions_from_leads(leads: list[dict]) -> list[int]:
    """从风险线索中提取待办，返回新创建的 action id 列表"""
    now = time.time()
    created = []

    for lead in leads:
        wxid = lead["wxid"]
        level = lead["risk_level"]
        reasons = lead.get("risk_reasons", [])
        silence = lead.get("silence_days", 0)

        # 检查是否已有同类未完成待办
        existing = _has_pending_action(wxid)
        if existing:
            continue

        if level == "high" and silence > 7:
            aid = create_action(
                wxid=wxid,
                action_type="activate",
                description=f"激活沉默客户 {lead['nickname']}（{silence}天未联系）",
                priority="high",
                source="risk_engine",
                ai_suggestion="发送问候消息，询问是否有新的需求",
            )
            created.append(aid)

        elif level == "high" and any("跟进日" in r for r in reasons):
            aid = create_action(
                wxid=wxid,
                action_type="followup",
                description=f"跟进 {lead['nickname']}（计划跟进日已过）",
                priority="high",
                source="risk_engine",
            )
            created.append(aid)

        elif level == "medium" and silence > 3:
            aid = create_action(
                wxid=wxid,
                action_type="followup",
                description=f"联系 {lead['nickname']}（{silence}天未互动）",
                priority="medium",
                source="risk_engine",
            )
            created.append(aid)

        elif level == "medium" and any("未回复" in r for r in reasons):
            aid = create_action(
                wxid=wxid,
                action_type="reply",
                description=f"回复 {lead['nickname']} 的消息",
                priority="high",
                source="new_message",
            )
            created.append(aid)

    return created


def extract_action_from_message(wxid: str, content: str, nickname: str = ""):
    """从新消息内容提取待办（简单关键词匹配）"""
    existing = _has_pending_action(wxid)
    if existing:
        return None

    name = nickname or wxid

    # 关键词 → 待办类型
    keywords_actions = [
        (["来版纳", "来西双版纳", "飞过去", "过去看", "过去一趟"], "confirm", f"确认 {name} 行程"),
        (["多少钱", "价格", "报价", "费用"], "reply", f"回复 {name} 价格咨询"),
        (["看看", "带看", "参观", "实地"], "confirm", f"安排 {name} 带看"),
        (["签约", "定金", "合同", "付首付"], "followup", f"推进 {name} 签约"),
    ]

    for keywords, action_type, desc in keywords_actions:
        if any(kw in content for kw in keywords):
            return create_action(
                wxid=wxid,
                action_type=action_type,
                description=desc,
                priority="high" if action_type in ("reply", "confirm") else "medium",
                source="new_message",
            )

    # 默认：新消息待回复
    return create_action(
        wxid=wxid,
        action_type="reply",
        description=f"回复 {name}",
        priority="medium",
        source="new_message",
    )


def _has_pending_action(wxid: str) -> bool:
    """检查是否已有未完成的待办"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM actions WHERE wxid = ? AND status = 'pending'",
        (wxid,),
    ).fetchone()
    conn.close()
    return row[0] > 0


def get_today_actions() -> list[dict]:
    """获取今日待办列表"""
    return get_pending_actions(limit=20)
