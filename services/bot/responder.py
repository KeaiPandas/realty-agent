"""Bot LLM 回复生成"""
from __future__ import annotations

from pathlib import Path

import yaml
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from services.bot.models import BotConversation, BotContactSettings
from services.bot.conversation import ConversationManager

# 加载屏蔽词
_block_words: list[str] = []


def _load_block_words():
    global _block_words
    try:
        bot_cfg_path = Path(__file__).parent.parent.parent / "config" / "bot.yaml"
        with open(bot_cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        _block_words = cfg.get("block_words", [])
    except Exception:
        _block_words = []


_load_block_words()


def is_blocked(content: str) -> bool:
    """检查消息是否包含屏蔽词"""
    return any(w in content for w in _block_words)


def is_nonsense(content: str) -> bool:
    """过滤无意义消息（系统消息、红包、位置等）"""
    if not content or not content.strip():
        return True
    # 系统消息特征
    if content.startswith("<") and content.endswith(">"):
        return True
    # 红包
    if "[微信红包]" in content or "领取红包" in content:
        return True
    # 位置分享
    if "位置分享" in content or "poi:" in content.lower():
        return True
    # 表情包/贴纸（纯符号）
    stripped = content.strip()
    if stripped and all(ord(c) > 0x1F000 or c in "[]" for c in stripped):
        return True
    return False


def generate_reply(conv: BotConversation,
                   conv_mgr: ConversationManager) -> str:
    """生成 AI 回复"""
    try:
        prompts = _load_prompts()
        cs_prompt = prompts.get("customer_service", {})
        system_text = cs_prompt.get("system", "")

        cs = conv_mgr.get_settings(conv.wxid)
        if cs and cs.system_prompt_override:
            system_text = cs.system_prompt_override

        user_template = cs_prompt.get("user_template", "")
        context_msgs = conv.messages[-settings.BOT_CONTEXT_MESSAGES:]
        chat_history = "\n".join(
            f"[{'客户' if m.is_from_customer else '我方'}] {m.content}"
            for m in context_msgs[:-1]
        ) if context_msgs else "（无历史记录）"

        latest = context_msgs[-1].content if context_msgs else ""
        user_text = user_template.format(
            customer_info=f"昵称: {conv.nickname}\n微信号: {conv.wxid}",
            chat_history=chat_history,
            latest_message=latest,
        ) if user_template else latest

        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0.7,
            max_tokens=200,
        )
        result = llm.invoke([
            SystemMessage(content=system_text),
            HumanMessage(content=user_text),
        ])
        return result.content.strip()
    except Exception as e:
        print(f"[Bot] LLM 生成回复出错: {e}")
        return ""


def _load_prompts() -> dict:
    prompts_path = Path(__file__).parent.parent.parent / settings.PROMPTS_FILE
    with open(prompts_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
