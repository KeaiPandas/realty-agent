"""微信相关工具 — 数据库解密、联系人搜索、消息提取"""
import sqlite3
from pathlib import Path

from langchain_core.tools import tool


# 缓存解密后的数据库路径，避免重复解密
_db_cache: dict = {}


def _get_wx_account() -> dict:
    """获取微信账号信息（wxid, key, wx_dir）"""
    from adapters.decrypt import get_wx_info

    wx_info = get_wx_info()
    if isinstance(wx_info, list) and wx_info:
        info = wx_info[0]
        return {
            "wxid": info.get("wxid", ""),
            "key": info.get("key", ""),
            "wx_dir": info.get("wx_dir", ""),
            "version": info.get("version", ""),
        }
    raise RuntimeError("未检测到微信进程，请确保微信已登录并运行")


def _ensure_decrypted() -> dict:
    """确保数据库已解密，返回 {name: path}"""
    global _db_cache
    if _db_cache:
        return _db_cache

    from adapters.decrypt import get_wx_info
    from config import settings
    from pywxdump import decrypt as wx_decrypt

    account = _get_wx_account()
    wx_dir = account["wx_dir"]
    key = account["key"]

    data_dir = Path(__file__).parent.parent.parent / settings.DATA_DIR
    data_dir.mkdir(exist_ok=True)

    msg_dir = Path(wx_dir) / "Msg"
    db_files = {
        name: msg_dir / f"{name}.db"
        for name in settings.WECHAT_DB_NAMES
    }
    multi_dir = msg_dir / "Multi"
    if multi_dir.exists():
        for f in sorted(multi_dir.glob("MSG*.db")):
            db_files[f.stem] = f

    for name, src_path in db_files.items():
        if not src_path.exists():
            continue
        dst = data_dir / f"{name}_decrypted.db"
        try:
            wx_decrypt(key, str(src_path), str(dst))
            _db_cache[name] = str(dst)
        except Exception as e:
            _db_cache[name] = None

    return _db_cache


@tool
def get_wechat_info() -> dict:
    """获取当前登录的微信账号信息，包括 wxid、数据目录、版本号。无需参数。"""
    return _get_wx_account()


@tool
def decrypt_wechat_db(wx_dir: str = "") -> dict:
    """解密微信本地数据库文件（MicroMsg.db、ChatMsg.db 等）。

    Args:
        wx_dir: 微信数据目录，留空则自动检测。
    Returns:
        解密后的数据库路径字典，如 {"MicroMsg": "path/to/db", ...}
    """
    global _db_cache
    _db_cache = {}

    if wx_dir:
        from adapters.decrypt import decrypt_db, get_wx_info
        from config import settings

        wx_info = get_wx_info()
        key = ""
        if isinstance(wx_info, list) and wx_info:
            key = wx_info[0].get("key", "")

        data_dir = Path(__file__).parent.parent.parent / settings.DATA_DIR
        data_dir.mkdir(exist_ok=True)
        msg_dir = Path(wx_dir) / "Msg"

        for name in settings.WECHAT_DB_NAMES:
            src = msg_dir / f"{name}.db"
            if src.exists():
                dst = data_dir / f"{name}_decrypted.db"
                decrypt_db(str(src), key, str(dst))
                _db_cache[name] = str(dst)

        multi = msg_dir / "Multi"
        if multi.exists():
            for f in sorted(multi.glob("MSG*.db")):
                dst = data_dir / f"{f.stem}_decrypted.db"
                decrypt_db(str(f), key, str(dst))
                _db_cache[f.stem] = str(dst)
    else:
        _ensure_decrypted()

    return {k: v for k, v in _db_cache.items() if v}


@tool
def search_wechat_contact(name: str) -> list[dict]:
    """按姓名、昵称或备注模糊搜索微信联系人。

    Args:
        name: 搜索关键词
    Returns:
        匹配的联系人列表，每项包含 wxid, nickname, alias, remark
    """
    db_paths = _ensure_decrypted()
    micromsg_db = db_paths.get("MicroMsg")
    if not micromsg_db:
        raise RuntimeError("MicroMsg.db 未解密，请先调用 decrypt_wechat_db")

    conn = sqlite3.connect(micromsg_db)
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
    results = []
    for row in cur.fetchall():
        results.append(
            {"wxid": row[0], "nickname": row[1], "alias": row[2], "remark": row[3]}
        )
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
    from adapters.extract import extract_dm_messages, format_dm_messages
    from config import settings

    db_paths = _ensure_decrypted()
    if not db_paths.get("MicroMsg"):
        raise RuntimeError("数据库未解密，请先调用 decrypt_wechat_db")

    messages = extract_dm_messages(
        db_paths, wxid, date=date or None, limit=limit or settings.DM_MSG_LIMIT
    )
    if not messages:
        return f"未找到与 {wxid} 的私聊消息"

    return format_dm_messages(wxid, messages, date or None)
