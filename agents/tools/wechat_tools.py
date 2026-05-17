"""微信相关工具 — 数据库解密、联系人搜索、消息提取"""
import sqlite3
from pathlib import Path

from adapters.db_layout import get_contact_db, get_message_dbs
from langchain_core.tools import tool

# 缓存解密后的数据库路径，避免重复解密
_db_cache: dict = {}


def _get_or_decrypt_db_paths() -> dict:
    """获取解密后的数据库路径（带缓存）"""
    global _db_cache
    if _db_cache:
        return _db_cache

    from adapters.decrypt import decrypt_all_databases
    _db_cache = decrypt_all_databases()
    return _db_cache


@tool
def get_wechat_info() -> dict:
    """获取当前登录的微信账号信息，包括 wxid、数据目录、版本号。无需参数。"""
    from adapters.db_layout import detect_wechat_version
    version = detect_wechat_version()
    from config import settings
    return {
        "version": version,
        "data_dir": settings.WECHAT_DATA_DIR,
    }


@tool
def decrypt_wechat_db() -> dict:
    """解密微信本地数据库文件。无需参数，自动检测版本并解密。

    Returns:
        解密后的数据库路径字典，如 {"contact": "path/to/db", ...}
    """
    global _db_cache
    _db_cache = {}
    _db_cache = decrypt_all_databases()
    return {k: v for k, v in _db_cache.items() if v}


@tool
def search_wechat_contact(name: str) -> list[dict]:
    """按姓名、昵称或备注模糊搜索微信联系人。

    Args:
        name: 搜索关键词
    Returns:
        匹配的联系人列表，每项包含 wxid, nickname, alias, remark
    """
    db_paths = _get_or_decrypt_db_paths()
    contact_db = get_contact_db(db_paths)
    if not contact_db:
        raise RuntimeError("联系人数据库未解密，请先调用 decrypt_wechat_db")

    conn = sqlite3.connect(contact_db)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT UserName, NickName, Alias, Remark
        FROM Contact
        WHERE (NickName LIKE ? OR Remark LIKE ?)
        AND UserName NOT LIKE '%%@chatroom'
        AND UserName NOT LIKE 'gh_%%'
        """,
        (f"%{name}%", f"%{name}%"),
    )
    results = [
        {"wxid": row[0], "nickname": row[1], "alias": row[2], "remark": row[3]}
        for row in cur.fetchall()
    ]
    conn.close()
    return results


@tool
def extract_dm_messages(wxid: str, date: str = "", limit: int = 0) -> str:
    """提取指定微信联系人的私聊消息，返回格式化的聊天文本。

    Args:
        wxid: 联系人的微信ID（如 wxid_xxx 或直接微信号）
        date: 可选，过滤日期（YYYY-MM-DD），留空提取全部
        limit: 最多提取条数，0使用配置默认值
    Returns:
        格式化的聊天记录文本
    """
    from adapters.extract import extract_dm_messages as _extract, format_dm_messages
    from config import settings

    db_paths = _get_or_decrypt_db_paths()
    if not get_contact_db(db_paths):
        raise RuntimeError("数据库未解密，请先调用 decrypt_wechat_db")

    messages = _extract(
        db_paths, wxid, date=date or None, limit=limit or settings.DM_MSG_LIMIT
    )
    if not messages:
        return f"未找到与 {wxid} 的私聊消息"

    return format_dm_messages(wxid, messages, date or None)
