"""AI 话术生成 — 读取 action 上下文 + 客户消息历史，调用 LLM 生成回复话术"""
import json

from config import settings


def generate_reply(action_id: int, force: bool = False) -> dict:
    """根据 action 生成 AI 回复话术。已生成的直接返回缓存。

    Args:
        action_id: 行动项 ID
        force: 是否强制重新生成（忽略缓存）

    Returns: { wxid, nickname, desc, draft }
    """
    from services.db import get_conn, get_messages

    conn = get_conn()
    row = conn.execute(
        "SELECT a.*, c.nickname, c.stage, c.profile_json, c.risk_level "
        "FROM actions a LEFT JOIN customers c ON a.wxid = c.wxid "
        "WHERE a.id = ?",
        (action_id,),
    ).fetchone()

    if not row:
        conn.close()
        return {"error": "action 不存在"}

    action = dict(row)
    wxid = action["wxid"]
    nickname = action.get("nickname") or wxid
    desc = action.get("description") or ""

    # 如果已有缓存且不强制刷新，直接返回
    cached_draft = action.get("reply_draft")
    if cached_draft and not force:
        conn.close()
        return {
            "wxid": wxid,
            "nickname": nickname,
            "desc": desc,
            "draft": cached_draft,
        }

    # 解析客户画像
    profile = {}
    try:
        profile = json.loads(action.get("profile_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    # 获取最近消息历史
    messages = get_messages(wxid, limit=20)
    chat_history = _format_history(messages)

    # 最近一条客户消息
    last_customer_msg = ""
    for m in reversed(messages):
        if m.get("is_from_customer"):
            last_customer_msg = m.get("content", "")
            break

    # 调用 LLM 生成话术
    draft = _call_llm(nickname, profile, chat_history, last_customer_msg, desc)

    # 持久化到 DB
    conn.execute(
        "UPDATE actions SET reply_draft = ? WHERE id = ?",
        (draft, action_id),
    )
    conn.commit()
    conn.close()

    return {
        "wxid": wxid,
        "nickname": nickname,
        "desc": desc,
        "draft": draft,
    }


def _format_history(messages: list[dict]) -> str:
    """格式化消息历史为文本"""
    lines = []
    for m in messages[-10:]:  # 只取最近 10 条
        role = "客户" if m.get("is_from_customer") else "我"
        content = m.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _call_llm(nickname: str, profile: dict, chat_history: str,
              last_message: str, action_desc: str) -> str:
    """调用 LLM 生成回复话术"""
    try:
        from pathlib import Path
        import yaml
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        prompts_path = Path(__file__).parent.parent.parent / settings.PROMPTS_FILE
        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f) or {}

        cs_cfg = prompts.get("customer_service", {})
        system_text = cs_cfg.get("system", "")

        # 构建客户信息摘要
        customer_info_parts = []
        customer_info_parts.append(f"姓名: {nickname}")
        if profile.get("budget_total_wan"):
            customer_info_parts.append(f"预算: {profile['budget_total_wan']}万")
        if profile.get("preferred_area"):
            customer_info_parts.append(f"意向区域: {profile['preferred_area']}")
        if profile.get("purchase_purpose"):
            customer_info_parts.append(f"目的: {profile['purchase_purpose']}")
        if profile.get("followup_stage"):
            customer_info_parts.append(f"阶段: {profile['followup_stage']}")
        customer_info = "\n".join(customer_info_parts)

        # 构建 action 上下文
        context = f"[行动建议: {action_desc}]\n\n" if action_desc else ""

        user_text = (
            f"客户信息：\n{customer_info}\n\n"
            f"最近对话记录：\n{chat_history}\n\n"
            f"客户最新消息：\n{last_message or '（无最新消息，主动跟进）'}\n\n"
            f"{context}"
            f"请直接生成一条发给客户的微信消息，自然、简短、像真人。"
        )

        llm = ChatOpenAI(
            model=settings.REPLY_LLM_MODEL,
            api_key=settings.REPLY_LLM_API_KEY,
            base_url=settings.REPLY_LLM_BASE_URL,
            temperature=0.7,
            max_tokens=200,
        )
        result = llm.invoke([
            SystemMessage(content=system_text),
            HumanMessage(content=user_text),
        ])
        return result.content.strip()

    except Exception as e:
        # LLM 调用失败时返回简单模板
        return f"{nickname}您好！好久没联系了，最近有什么新的需求吗？有新的项目优惠可以了解下 😊"
