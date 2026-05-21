"""
从解密后的微信数据库中提取聊天记录
兼容 3.x 和 4.x 数据库结构
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from services.sync.db_layout import get_contact_db, get_message_dbs


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
    """在数据库中查找消息表（3.x: MSG 表）"""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for t in tables:
        if t.upper() == "MSG":
            return t
    return None


def _find_msg_table_for_contact(conn, contact_id: str) -> str | None:
    """4.x: 通过 MD5(username) 找到对应的消息表"""
    table_hash = hashlib.md5(contact_id.encode()).hexdigest()
    table_name = f"Msg_{table_hash}"
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return table_name if result else None


def _get_sender_map(conn) -> dict[int, str]:
    """4.x: 构建 real_sender_id → username 映射（来自 Name2Id）"""
    result = {}
    try:
        for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            result[row[0]] = row[1]
    except Exception:
        pass
    return result


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
            cursor.execute("SELECT username, nick_name FROM contact")
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
                SELECT username, nick_name, alias, remark
                FROM contact
                WHERE username NOT LIKE '%%@chatroom'
                  AND username NOT LIKE 'gh_%%'
                  AND username NOT IN ('notifymessage', 'weixin', 'fmessage',
                                       'filehelper', 'floatbottle', 'medianote')
                  AND nick_name IS NOT NULL AND nick_name != ''
                ORDER BY nick_name
            """)
            for row in cursor.fetchall():
                contacts.append({
                    "wxid": row["username"],
                    "nickname": row["nick_name"],
                    "alias": row["alias"] or "",
                    "remark": row["remark"] or "",
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
            try:
                cursor.execute("SELECT UserName, NickName, Alias, Remark FROM Contact")
                for row in cursor.fetchall():
                    aliases[row[0]] = {
                        "nickname": row[1] or "",
                        "alias": row[2] or "",
                        "remark": row[3] or "",
                    }
            except Exception:
                try:
                    cursor.execute("SELECT username, nick_name, alias, remark FROM contact")
                    for row in cursor.fetchall():
                        aliases[row[0]] = {
                            "nickname": row[1] or "",
                            "alias": row[2] or "",
                            "remark": row[3] or "",
                        }
                except Exception:
                    pass
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

            # 3.x: MSG 表 + StrTalker
            msg_table = _find_msg_table(conn)
            if msg_table:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT StrTalker, COUNT(*) as cnt
                    FROM {msg_table}
                    WHERE Type = 1
                      AND StrTalker NOT LIKE ? ESCAPE '\\\\'
                      AND StrTalker NOT LIKE ?
                      AND StrTalker NOT IN ('filehelper', 'floatbottle', 'medianote')
                    GROUP BY StrTalker
                """, ('%@chatroom', 'gh_%'))
                for row in cursor.fetchall():
                    contact_msgs[row[0]] = contact_msgs.get(row[0], 0) + row[1]
            else:
                # 4.x: 遍历 Msg_<hash> 表，用 Name2Id 反查 username
                sender_map = _get_sender_map(conn)
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%%'"
                ).fetchall()]
                for tbl in tables:
                    try:
                        cnt = conn.execute(
                            f"SELECT COUNT(*) FROM {tbl} WHERE local_type = 1"
                        ).fetchone()[0]
                        if cnt > 0:
                            table_hash = tbl[4:]
                            for uid, name in sender_map.items():
                                if hashlib.md5(name.encode()).hexdigest() == table_hash:
                                    if not name.endswith("@chatroom") and not name.startswith("gh_"):
                                        contact_msgs[name] = contact_msgs.get(name, 0) + cnt
                                    break
                    except Exception:
                        continue
            conn.close()
        except Exception:
            pass

    # Fallback: 如果消息表为空（WCDB 压缩导致不可读），从 session 表获取联系人
    if not contact_msgs:
        session_db = db_paths.get("session", "")
        if session_db and Path(session_db).exists():
            try:
                conn = sqlite3.connect(session_db)
                for row in conn.execute(
                    "SELECT username, last_timestamp FROM SessionTable"
                ).fetchall():
                    wxid = row[0]
                    if (wxid.endswith("@chatroom") or wxid.startswith("gh_")
                            or wxid in ("filehelper", "floatbottle", "medianote",
                                        "notifymessage", "weixin", "fmessage",
                                        "newsapp", "floatbottle")):
                        continue
                    contact_msgs[wxid] = row[1] or 1
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

            # 3.x: MSG 表 + StrTalker
            msg_table = _find_msg_table(conn)
            if msg_table:
                conn.row_factory = sqlite3.Row
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
                    sender = nicknames.get(contact_id, contact_id)

                    results.append({
                        "time": msg_time.strftime("%Y-%m-%d %H:%M"),
                        "sender": sender,
                        "content": content.strip(),
                        "type": MSG_TYPES.get(row["Type"], f"类型{row['Type']}"),
                        "is_from_customer": True,
                    })

                conn.close()
                continue

            # 4.x: Msg_<MD5(username)> 表
            msg_table_v4 = _find_msg_table_for_contact(conn, contact_id)
            if not msg_table_v4:
                conn.close()
                continue

            sender_map = _get_sender_map(conn)
            # 找到自己的 rowid（is_session=0 的那条）
            self_rowid = None
            try:
                row = conn.execute(
                    "SELECT rowid FROM Name2Id WHERE is_session = 0 LIMIT 1"
                ).fetchone()
                if row:
                    self_rowid = row[0]
            except Exception:
                pass

            cursor = conn.cursor()
            if filter_date:
                cursor.execute(
                    f"""
                    SELECT local_id, create_time, local_type, message_content, real_sender_id
                    FROM {msg_table_v4}
                    WHERE local_type = 1
                      AND create_time >= ?
                      AND create_time < ?
                    ORDER BY create_time ASC
                    LIMIT ?
                    """,
                    (start_ts, end_ts, limit),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT local_id, create_time, local_type, message_content, real_sender_id
                    FROM {msg_table_v4}
                    WHERE local_type = 1
                    ORDER BY create_time ASC
                    LIMIT ?
                    """,
                    (limit,),
                )

            for row in cursor.fetchall():
                content = row[3]  # message_content
                if not isinstance(content, str):
                    continue  # 跳过压缩/二进制内容
                msg_time = datetime.fromtimestamp(row[1])
                sender_name = sender_map.get(row[4], contact_id)  # real_sender_id
                is_self = (self_rowid is not None and row[4] == self_rowid)

                results.append({
                    "time": msg_time.strftime("%Y-%m-%d %H:%M"),
                    "sender": sender_name,
                    "content": content.strip(),
                    "type": MSG_TYPES.get(row[2], f"类型{row[2]}"),
                    "is_from_customer": not is_self,
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
