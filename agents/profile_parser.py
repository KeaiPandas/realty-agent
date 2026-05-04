import asyncio
import json
from pathlib import Path

import yaml
from langchain_openai import ChatOpenAI

from config import settings
from models import CustomerProfile


def load_prompts() -> dict:
    prompts_path = Path(__file__).parent.parent / "prompts.yaml"
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
        temperature=0,
        max_tokens=4096,
    )

    # 在prompt中强制要求JSON输出
    json_instruction = (
        "\n\n**重要：你的回复必须是纯JSON格式，不要包含markdown代码块标记（不要用```），"
        "直接输出JSON对象。**"
    )

    response = await llm.ainvoke(
        [
            {"role": "system", "content": system_prompt + json_instruction},
            {"role": "user", "content": user_prompt},
        ]
    )

    # 手动解析JSON（GLM可能返回带markdown代码块的JSON）
    content = response.content.strip()
    if content.startswith("```"):
        # 去掉 ```json 和 ```
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(content)
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
