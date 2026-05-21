import asyncio
import json
from pathlib import Path

import yaml
from langchain_openai import ChatOpenAI

from config import settings
from models import CustomerProfile


def load_prompts() -> dict:
    prompts_path = Path(__file__).parent.parent / settings.PROMPTS_FILE
    with open(prompts_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_profile_parser_prompt(prompts: dict) -> str:
    return prompts["profile_parser"]["system"]


async def parse_chat_to_profile(
    chat_content: str,
    existing_profile: dict | None = None,
) -> CustomerProfile:
    """AI解析聊天记录 → 69字段客户画像

    Args:
        chat_content: 格式化的聊天记录文本
        existing_profile: 已有画像（增量更新），None表示新建

    Returns:
        CustomerProfile 实例
    """
    prompts = load_prompts()
    system_prompt = get_profile_parser_prompt(prompts)

    user_template = prompts["profile_parser"]["user_template"]
    user_prompt = user_template.format(
        chat_content=chat_content,
        existing_profile=json.dumps(
            existing_profile, ensure_ascii=False, indent=2
        ) if existing_profile else "无（新客户）",
    )

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        timeout=60,
        max_retries=1,
    )

    # 在prompt中强制要求JSON输出
    json_instruction = (
        "\n\n**重要：只输出有值的字段，省略值为null的字段。"
        "回复必须是纯JSON格式，不要包含markdown代码块标记（不要用```），"
        "直接输出JSON对象。**"
    )

    response = await asyncio.wait_for(
        llm.ainvoke(
            [
                {"role": "system", "content": system_prompt + json_instruction},
                {"role": "user", "content": user_prompt},
            ]
        ),
        timeout=90,
    )

    # 手动解析JSON（GLM可能返回带markdown代码块的JSON）
    content = response.content.strip()
    if content.startswith("```"):
        # 去掉 ```json 和 ```
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(content)

    # 修正LLM返回的类型偏差
    # 字符串字段：LLM可能返回int
    for key in ("phone", "existing_properties", "wechat_name", "douyin_name"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            data[key] = str(data[key])
    # 数值字段：LLM可能返回字符串
    for key in ("age", "family_members", "stay_duration_days", "purchase_count",
                "annual_stay_months", "area_sqm", "budget_total_wan", "price_per_sqm",
                "down_payment", "monthly_payment"):
        if key in data and data[key] is not None:
            try:
                data[key] = float(data[key])
                if data[key] == int(data[key]):
                    data[key] = int(data[key])
            except (ValueError, TypeError):
                pass

    return CustomerProfile(**data)


def parse_chat_to_profile_sync(
    chat_content: str,
    existing_profile: dict | None = None,
) -> CustomerProfile:
    """同步版本的AI解析"""
    return asyncio.run(parse_chat_to_profile(chat_content, existing_profile))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python profile_parser.py <chat_file.txt>")
        sys.exit(1)

    chat_file = Path(sys.argv[1])
    if not chat_file.exists():
        print(f"文件不存在: {chat_file}")
        sys.exit(1)

    chat_content = chat_file.read_text(encoding="utf-8")
    print("正在解析聊天记录...")
    profile = parse_chat_to_profile_sync(chat_content)

    print("\n=== 解析结果 ===")
    for field_name, value in profile.model_dump().items():
        if value is not None:
            print(f"  {field_name}: {value}")

    non_null = sum(1 for v in profile.model_dump().values() if v is not None)
    print(f"\n共提取 {non_null} 个字段")
