"""同步工具 — 飞书多维表格、钉钉AI表"""
import json

from langchain_core.tools import tool


@tool
def sync_profile_to_feishu(
    profile: str,
    base_token: str = "",
    table_id: str = "",
) -> dict:
    """将客户画像同步到飞书多维表格。按微信号唯一键去重：有则更新，无则创建。

    Args:
        profile: 画像JSON字符串（必须包含wechat_id字段）
        base_token: 飞书base token，留空使用.env配置
        table_id: 飞书table id，留空使用.env配置
    Returns:
        {"action": "created"|"updated", "record_id": "..."}
    """
    from config import settings
    from models import CustomerProfile
    from services.feishu_service import sync_profile_to_feishu as _sync

    data = json.loads(profile)
    p = CustomerProfile(**data)
    bt = base_token or settings.FEISHU_BASE_TOKEN
    tid = table_id or settings.FEISHU_TABLE_ID

    if not bt or not tid:
        raise ValueError("未配置飞书 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID")

    result = _sync(p, bt, tid)
    return {"action": result["action"], "record_id": result.get("record_id", "")}


@tool
def query_feishu_by_wechat(wechat_id: str, base_token: str = "", table_id: str = "") -> dict:
    """按微信号查询飞书多维表格中的客户记录。

    Args:
        wechat_id: 微信号（飞书唯一键）
        base_token: 飞书base token，留空使用.env配置
        table_id: 飞书table id，留空使用.env配置
    Returns:
        匹配的记录，或空字典表示未找到
    """
    from config import settings
    from services.feishu_service import query_record_by_wechat_id

    bt = base_token or settings.FEISHU_BASE_TOKEN
    tid = table_id or settings.FEISHU_TABLE_ID

    result = query_record_by_wechat_id(wechat_id, bt, tid)
    return result or {}


@tool
def query_feishu_by_phone(phone: str, base_token: str = "", table_id: str = "") -> dict:
    """按手机号查询飞书多维表格中的客户记录。

    Args:
        phone: 手机号
        base_token: 飞书base token，留空使用.env配置
        table_id: 飞书table id，留空使用.env配置
    Returns:
        匹配的记录，或空字典表示未找到
    """
    from config import settings
    from services.feishu_service import query_record_by_phone

    bt = base_token or settings.FEISHU_BASE_TOKEN
    tid = table_id or settings.FEISHU_TABLE_ID

    result = query_record_by_phone(phone, bt, tid)
    return result or {}


@tool
def sync_profile_to_dingtalk(
    profile: str,
    base_id: str = "",
    table_id: str = "",
) -> dict:
    """将客户画像同步到钉钉AI表格（自动创建或更新）。

    Args:
        profile: 画像JSON字符串
        base_id: 钉钉base id，留空使用.env配置
        table_id: 钉钉table id，留空使用.env配置
    Returns:
        {"action": "created"|"updated", "record_id": "..."}
    """
    from config import settings
    from models import CustomerProfile
    from services.dingtalk_service import sync_profile_to_dingtalk as _sync

    data = json.loads(profile)
    p = CustomerProfile(**data)
    bid = base_id or settings.DINGTALK_BASE_ID
    tid = table_id or settings.DINGTALK_TABLE_ID

    if not bid or not tid:
        raise ValueError("未配置钉钉 DINGTALK_BASE_ID / DINGTALK_TABLE_ID")

    result = _sync(p, bid, tid)
    return {"action": result["action"], "record_id": result.get("record_id", "")}
