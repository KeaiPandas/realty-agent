"""
从解密后的微信数据库中提取聊天记录
兼容 3.x 和 4.x 数据库结构（表结构相同，路径不同）
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from adapters.db_layout import get_contact_db, get_message_dbs


MSG_TYPES = {
    1: "文本",
    3: "图片",
    34: "语音",
    43: "视频",
    47: "表情",
    49: "链接/文件",
    10000: "系统消息",
}


def _get_dm_msg_limit() -> int:
    from config import settings
    return settings.DM_MSG_LIMIT


def _find_msg_table(conn) -> str | None:
    """在数据库中查找消息表（大小写不敏感）"""
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for t in tables:
        if t.upper() == "MSG":
            return t
    return None


# ── 联系人查询 ────────────────────────────────────────────

def get_contact_nicknames(db_path: str) -> dict[str, str]:
    """获取所有联系人的昵称映射 {wxid: 昵称}"""
    if not db_path:
        return {}
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    nicknames = {}
    try:
        cursor.execute("SELECT UserName, NickName FROM Contact")
        for row in cursor.fetchall():
            nicknames[row[0]] = row[1]
    except Exception:
        try:
            cursor.execute("SELECT userName, nickName FROM rcontact")
            for row in cursor.fetchall():
                nicknames[row[0]] = row[1]
        except Exception:
            pass

    conn.close()
    return nicknames


def get_dm_contacts(db_path: str) -> list[dict]:
    """获取所有私聊联系人（排除群聊、公众号、系统号）"""
    if not db_path:
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    contacts = []
    try:
        cursor.execute("""
            SELECT UserName, NickName, Alias, Remark
            FROM Contact
            WHERE UserName NOT LIKE '%%@chatroom'
              AND UserName NOT LIKE 'gh_%%'
              AND UserName NOT IN ('filehelper', 'floatbottle', 'medianote')
              AND NickName IS NOT NULL
              AND NickName != ''
            ORDER BY NickName
        """)
        for row in cursor.fetchall():
            contacts.append({
                "wxid": row["UserName"],
                "nickname": row["NickName"],
                "alias": row["Alias"] or "",
                "remark": row["Remark"] or "",
            })
    except Exception:
        try:
            cursor.execute("""
                SELECT userName, nickName, alias
                FROM rcontact
                WHERE userName NOT LIKE '%%@chatroom'
                  AND userName NOT LIKE 'gh_%%'
                  AND userName NOT IN ('filehelper', 'floatbottle', 'medianote')
                  AND nickName IS NOT NULL AND nickName != ''
            """)
            for row in cursor.fetchall():
                contacts.append({
                    "wxid": row["userName"],
                    "nickname": row["nickName"],
                    "alias": row["alias"] or "",
                    "remark": "",
                })
        except Exception:
            pass

    conn.close()
    return contacts


def get_dm_contacts_with_messages(db_paths: dict) -> list[dict]:
    """获取有实际私聊消息的联系人（从消息库筛选，排除群聊）"""
    contact_db = get_contact_db(db_paths)
    nicknames = get_contact_nicknames(contact_db) if contact_db else {}

    # 获取别名信息
    aliases: dict[str, dict] = {}
    if contact_db:
        try:
            conn = sqlite3.connect(contact_db)
            cursor = conn.cursor()
            cursor.execute("SELECT UserName, NickName, Alias, Remark FROM Contact")
            for row in cursor.fetchall():
                aliases[row[0]] = {
                    "nickname": row[1] or "",
                    "alias": row[2] or "",
                    "remark": row[3] or "",
                }
            conn.close()
        except Exception:
            pass

    msg_dbs = get_message_dbs(db_paths)

    contact_msgs: dict[str, int] = {}
    for msg_db in msg_dbs:
        if not Path(msg_db).exists():
            continue
        try:
            conn = sqlite3.connect(msg_db)
            msg_table = _find_msg_table(conn)
            if not msg_table:
                conn.close()
                continue
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT StrTalker, COUNT(*) as cnt
                FROM {msg_table}
                WHERE Type = 1
                  AND StrTalker NOT LIKE ? ESCAPE '\\'
                  AND StrTalker NOT LIKE ?
                  AND StrTalker NOT IN ('filehelper', 'floatbottle', 'medianote')
                GROUP BY StrTalker
            """, ('%@chatroom', 'gh_%'))
            for row in cursor.fetchall():
                contact_msgs[row[0]] = contact_msgs.get(row[0], 0) + row[1]
            conn.close()
        except Exception:
            pass

    results = []
    for wxid, msg_count in sorted(contact_msgs.items(), key=lambda x: -x[1]):
        info = aliases.get(wxid, {})
        results.append({
            "wxid": wxid,
            "nickname": info.get("nickname") or nicknames.get(wxid, ""),
            "alias": info.get("alias", ""),
            "remark": info.get("remark", ""),
            "msg_count": msg_count,
        })
    return results


# ── 消息提取 ──────────────────────────────────────────────

def extract_dm_messages(
    db_paths: dict, contact_id: str,
    date: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 0,
) -> list[dict]:
    """提取指定联系人的私聊消息

    日期过滤优先级：date_start+date_end > date > 无过滤
    """
    if limit <= 0:
        limit = _get_dm_msg_limit()

    filter_date = True
    if date_start and date_end:
        start_ts = int(datetime.strptime(date_start, "%Y-%m-%d").timestamp())
        end_ts = int(
            (datetime.strptime(date_end, "%Y-%m-%d") + timedelta(days=1)).timestamp()
        )
    elif date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp())
        end_ts = int(
            (target_date + timedelta(days=1))
            .replace(hour=0, minute=0, second=0).timestamp()
        )
    else:
        filter_date = False
        start_ts = 0
        end_ts = 0

    contact_db = get_contact_db(db_paths)
    nicknames = get_contact_nicknames(contact_db) if contact_db else {}

    msg_dbs = get_message_dbs(db_paths)
    results = []

    for msg_db in msg_dbs:
        if not Path(msg_db).exists():
            continue
        try:
            conn = sqlite3.connect(msg_db)
            conn.row_factory = sqlite3.Row
            msg_table = _find_msg_table(conn)
            if not msg_table:
                conn.close()
                continue

            cursor = conn.cursor()

            if filter_date:
                cursor.execute(
                    f"""
                    SELECT localId, StrTalker, CreateTime, Type, StrContent
                    FROM {msg_table}
                    WHERE StrTalker = ?
                      AND Type = 1
                      AND CreateTime >= ?
                      AND CreateTime < ?
                    ORDER BY CreateTime ASC
                    LIMIT ?
                    """,
                    (contact_id, start_ts, end_ts, limit),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT localId, StrTalker, CreateTime, Type, StrContent
                    FROM {msg_table}
                    WHERE StrTalker = ?
                      AND Type = 1
                    ORDER BY CreateTime ASC
                    LIMIT ?
                    """,
                    (contact_id, limit),
                )

            for row in cursor.fetchall():
                content = row["StrContent"] or ""
                msg_time = datetime.fromtimestamp(row["CreateTime"])

                # 判断消息方向：StrTalker 是会话 ID，私聊中等于对方 wxid
                # 消息可能来自对方或自己，这里简单标记为对方消息
                # 后续可通过 BytesExtra 中的 sender 信息精确判断
                sender = nicknames.get(contact_id, contact_id)
                is_from_customer = True

                results.append({
                    "time": msg_time.strftime("%Y-%m-%d %H:%M"),
                    "sender": sender,
                    "content": content.strip(),
                    "type": MSG_TYPES.get(row["Type"], f"类型{row['Type']}"),
                    "is_from_customer": is_from_customer,
                })

            conn.close()
        except Exception as e:
            print(f"  读取 {msg_db} 出错: {e}")

    return results


def format_dm_messages(contact_name: str, messages: list[dict], date: str | None = None) -> str:
    """将DM消息格式化为文本，供AI处理"""
    if not messages:
        return f"与 {contact_name} 的私聊在 {date or '今天'} 没有消息。"

    lines = [f"=== 私聊对象: {contact_name} | 日期: {date or '今天'} ===\n"]

    for msg in messages:
        prefix = "客户" if msg.get("is_from_customer") else "我方"
        lines.append(f"[{msg['time']}] [{prefix}] {msg['content']}")

    return "\n".join(lines)
