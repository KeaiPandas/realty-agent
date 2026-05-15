"""画像解析与管理工具 — AI解析、保存、加载"""
import json
from pathlib import Path

from langchain_core.tools import tool


@tool
def parse_chat_to_profile(chat_content: str, existing_profile: str = "") -> dict:
    """用AI解析聊天记录，提取69字段客户画像。

    Args:
        chat_content: 聊天记录文本
        existing_profile: 已有画像JSON字符串（增量更新时传入），留空表示新客户
    Returns:
        69字段结构化客户画像字典
    """
    import asyncio
    import sys

    if sys.platform == "win32" and sys.version_info >= (3, 10):
        # Windows Python 3.14 可能已有事件循环
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()

    from agents.profile_parser import parse_chat_to_profile as _parse

    existing = None
    if existing_profile:
        try:
            existing = json.loads(existing_profile)
        except json.JSONDecodeError:
            existing = None

    profile = asyncio.run(_parse(chat_content, existing_profile=existing))
    return profile.model_dump(exclude_none=True)


@tool
def save_profile(profile: str, filepath: str = "") -> str:
    """将客户画像保存为JSON文件。

    Args:
        profile: 画像JSON字符串
        filepath: 保存路径，留空则自动生成到 data/ 目录
    Returns:
        保存的文件路径
    """
    data = json.loads(profile)

    if not filepath:
        from config import settings

        phone = data.get("phone", "unknown")
        name = data.get("name", "unknown")
        filepath = str(
            Path(__file__).parent.parent.parent
            / settings.DATA_DIR
            / f"profile_{name}_{phone}.json"
        )

    path = Path(filepath)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@tool
def load_profile(filepath: str) -> dict:
    """从JSON文件加载客户画像。

    Args:
        filepath: JSON文件路径
    Returns:
        客户画像字典
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")
    return json.loads(path.read_text(encoding="utf-8"))
