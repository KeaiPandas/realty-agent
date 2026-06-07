"""AI 每日情报简报生成"""
import json
import time
from datetime import datetime

from config import settings


def generate_briefing() -> dict:
    """生成今日情报简报"""
    from services.db import get_briefing, save_briefing, get_kpi_stats, get_customers_by_risk
    from services.leads.action_extractor import get_today_actions
    from services.leads.risk_engine import get_risk_leads

    today = datetime.now().strftime("%Y-%m-%d")

    # 检查缓存（今天已生成过就直接返回）
    cached = get_briefing(today)
    if cached:
        # content 可能是双重序列化的 JSON 字符串，需要解析
        raw_content = cached.get("content", "")
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
                return parsed
            except (json.JSONDecodeError, TypeError):
                return {"date": today, "summary": raw_content}
        return cached

    # 收集数据
    kpi = get_kpi_stats()
    risk_leads = get_risk_leads()
    actions = get_today_actions()

    high_risk = [l for l in risk_leads if l["risk_level"] == "high"]
    medium_risk = [l for l in risk_leads if l["risk_level"] == "medium"]

    # 尝试调用 LLM 生成简报
    summary = _generate_summary(kpi, high_risk, medium_risk, actions)

    result = {
        "date": today,
        "summary": summary,
        "new_leads": kpi["new_messages_today"],
        "risk_alerts": len(high_risk),
        "pending_actions": len(actions),
        "generated_at": time.time(),
    }

    save_briefing(today, json.dumps(result, ensure_ascii=False))
    return result


def _generate_summary(kpi: dict, high_risk: list, medium_risk: list,
                      actions: list) -> str:
    """调用 LLM 生成简报摘要"""
    try:
        from pathlib import Path
        import yaml
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        prompts_path = Path(__file__).parent.parent.parent / settings.PROMPTS_FILE
        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f) or {}

        briefing_cfg = prompts.get("daily_briefing", {})
        system_text = briefing_cfg.get("system", "")
        user_template = briefing_cfg.get("user_template", "")

        risk_desc = "\n".join(
            f"- {c['nickname']}: {', '.join(c.get('risk_reasons', []))}"
            for c in high_risk[:5]
        ) if high_risk else "无高风险客户"

        action_desc = "\n".join(
            f"- {a['description']}"
            for a in actions[:5]
        ) if actions else "无待办"

        user_text = user_template.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            new_messages_count=kpi.get("new_messages_today", 0),
            active_count=kpi.get("active_customers", 0),
            risk_leads=risk_desc,
            pending_actions=action_desc,
        ) if user_template else f"今日新增{kpi.get('new_messages_today', 0)}条消息，{len(high_risk)}个高风险客户"

        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0.3,
            max_tokens=200,
        )
        result = llm.invoke([
            SystemMessage(content=system_text),
            HumanMessage(content=user_text),
        ])
        return result.content.strip()
    except Exception as e:
        # LLM 调用失败时用模板降级
        parts = []
        if high_risk:
            names = ", ".join(c["nickname"] for c in high_risk[:3])
            parts.append(f"⚠️ {len(high_risk)}个高风险客户需关注: {names}")
        if kpi.get("new_messages_today", 0) > 0:
            parts.append(f"💬 今日新增{kpi['new_messages_today']}条客户消息")
        if actions:
            parts.append(f"📋 {len(actions)}个待办事项等待处理")
        if medium_risk:
            parts.append(f"🟡 {len(medium_risk)}个客户需要跟进")
        return " | ".join(parts) if parts else "暂无重要动态"
