"""Extract WeChat contacts and direct messages from decrypted SQLite DBs."""
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
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    for table in tables:
        if table.upper() == "MSG":
            return table
    return None


def _find_msg_table_for_contact(conn, contact_id: str) -> str | None:
    table_hash = hashlib.md5(contact_id.encode()).hexdigest()
    table_name = f"Msg_{table_hash}"
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return table_name if result else None


def _get_sender_map(conn) -> dict[int, str]:
    result = {}
    try:
        for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            result[row[0]] = row[1]
    except Exception:
        pass
    return result


def get_contact_nicknames(db_path: str) -> dict[str, str]:
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


def build_contact_search_terms(*values: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = (value or "").strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def get_contact_profiles(db_path: str) -> dict[str, dict]:
    if not db_path:
        return {}

    contacts = get_dm_contacts(db_path)
    profiles: dict[str, dict] = {}
    for contact in contacts:
        wxid = contact["wxid"]
        nickname = (contact.get("nickname") or "").strip()
        alias = (contact.get("alias") or "").strip()
        remark = (contact.get("remark") or "").strip()
        profiles[wxid] = {
            "wxid": wxid,
            "nickname": nickname,
            "alias": alias,
            "remark": remark,
            "display_name": remark or nickname or alias or wxid,
            "search_terms": build_contact_search_terms(alias, remark, nickname, wxid),
        }
    return profiles


def get_dm_contacts(db_path: str) -> list[dict]:
    if not db_path:
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    contacts = []
    try:
        cursor.execute(
            """
            SELECT UserName, NickName, Alias, Remark
            FROM Contact
            WHERE UserName NOT LIKE '%%@chatroom'
              AND UserName NOT LIKE 'gh_%%'
              AND UserName NOT IN ('filehelper', 'floatbottle', 'medianote')
              AND NickName IS NOT NULL
              AND NickName != ''
            ORDER BY NickName
            """
        )
        for row in cursor.fetchall():
            contacts.append(
                {
                    "wxid": row["UserName"],
                    "nickname": row["NickName"],
                    "alias": row["Alias"] or "",
                    "remark": row["Remark"] or "",
                }
            )
    except Exception:
        try:
            cursor.execute(
                """
                SELECT username, nick_name, alias, remark
                FROM contact
                WHERE username NOT LIKE '%%@chatroom'
                  AND username NOT LIKE 'gh_%%'
                  AND username NOT IN ('notifymessage', 'weixin', 'fmessage',
                                       'filehelper', 'floatbottle', 'medianote')
                  AND nick_name IS NOT NULL AND nick_name != ''
                ORDER BY nick_name
                """
            )
            for row in cursor.fetchall():
                contacts.append(
                    {
                        "wxid": row["username"],
                        "nickname": row["nick_name"],
                        "alias": row["alias"] or "",
                        "remark": row["remark"] or "",
                    }
                )
        except Exception:
            try:
                cursor.execute(
                    """
                    SELECT userName, nickName, alias
                    FROM rcontact
                    WHERE userName NOT LIKE '%%@chatroom'
                      AND userName NOT LIKE 'gh_%%'
                      AND userName NOT IN ('filehelper', 'floatbottle', 'medianote')
                      AND nickName IS NOT NULL AND nickName != ''
                    """
                )
                for row in cursor.fetchall():
                    contacts.append(
                        {
                            "wxid": row["userName"],
                            "nickname": row["nickName"],
                            "alias": row["alias"] or "",
                            "remark": "",
                        }
                    )
            except Exception:
                pass

    conn.close()
    return contacts


def get_dm_contacts_with_messages(db_paths: dict) -> list[dict]:
    contact_db = get_contact_db(db_paths)
    nicknames = get_contact_nicknames(contact_db) if contact_db else {}

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
            msg_table = _find_msg_table(conn)
            if msg_table:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT StrTalker, COUNT(*) as cnt
                    FROM {msg_table}
                    WHERE Type = 1
                      AND StrTalker NOT LIKE ? ESCAPE '\\\\'
                      AND StrTalker NOT LIKE ?
                      AND StrTalker NOT IN ('filehelper', 'floatbottle', 'medianote')
                    GROUP BY StrTalker
                    """,
                    ("%@chatroom", "gh_%"),
                )
                for row in cursor.fetchall():
                    contact_msgs[row[0]] = contact_msgs.get(row[0], 0) + row[1]
            else:
                sender_map = _get_sender_map(conn)
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%%'"
                    ).fetchall()
                ]
                for table in tables:
                    try:
                        count = conn.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE local_type = 1"
                        ).fetchone()[0]
                        if count <= 0:
                            continue
                        table_hash = table[4:]
                        for _, name in sender_map.items():
                            if hashlib.md5(name.encode()).hexdigest() == table_hash:
                                if not name.endswith("@chatroom") and not name.startswith("gh_"):
                                    contact_msgs[name] = contact_msgs.get(name, 0) + count
                                break
                    except Exception:
                        continue
            conn.close()
        except Exception:
            pass

    if not contact_msgs:
        session_db = db_paths.get("session", "")
        if session_db and Path(session_db).exists():
            try:
                conn = sqlite3.connect(session_db)
                for row in conn.execute("SELECT username, last_timestamp FROM SessionTable").fetchall():
                    wxid = row[0]
                    if (
                        wxid.endswith("@chatroom")
                        or wxid.startswith("gh_")
                        or wxid
                        in (
                            "filehelper",
                            "floatbottle",
                            "medianote",
                            "notifymessage",
                            "weixin",
                            "fmessage",
                            "newsapp",
                        )
                    ):
                        continue
                    contact_msgs[wxid] = row[1] or 1
                conn.close()
            except Exception:
                pass

    results = []
    for wxid, msg_count in sorted(contact_msgs.items(), key=lambda item: -item[1]):
        info = aliases.get(wxid, {})
        results.append(
            {
                "wxid": wxid,
                "nickname": info.get("nickname") or nicknames.get(wxid, ""),
                "alias": info.get("alias", ""),
                "remark": info.get("remark", ""),
                "msg_count": msg_count,
            }
        )
    return results


def extract_dm_messages(
    db_paths: dict,
    contact_id: str,
    date: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 0,
) -> list[dict]:
    if limit <= 0:
        limit = _get_dm_msg_limit()

    filter_date = True
    if date_start and date_end:
        start_ts = int(datetime.strptime(date_start, "%Y-%m-%d").timestamp())
        end_ts = int((datetime.strptime(date_end, "%Y-%m-%d") + timedelta(days=1)).timestamp())
    elif date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp())
        end_ts = int(
            (target_date + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()
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
                    results.append(
                        {
                            "time": msg_time.strftime("%Y-%m-%d %H:%M"),
                            "timestamp": row["CreateTime"],
                            "sender": sender,
                            "content": content.strip(),
                            "type": MSG_TYPES.get(row["Type"], f"类型{row['Type']}"),
                            "is_from_customer": True,
                            "_sort_ts": row["CreateTime"],
                            "_sort_id": row["localId"],
                        }
                    )

                conn.close()
                continue

            msg_table_v4 = _find_msg_table_for_contact(conn, contact_id)
            if not msg_table_v4:
                conn.close()
                continue

            sender_map = _get_sender_map(conn)
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
                content = row[3]
                if not isinstance(content, str):
                    continue
                msg_time = datetime.fromtimestamp(row[1])
                sender_name = sender_map.get(row[4], contact_id)
                is_self = self_rowid is not None and row[4] == self_rowid
                results.append(
                    {
                        "time": msg_time.strftime("%Y-%m-%d %H:%M"),
                        "timestamp": row[1],
                        "sender": sender_name,
                        "content": content.strip(),
                        "type": MSG_TYPES.get(row[2], f"类型{row[2]}"),
                        "is_from_customer": not is_self,
                        "_sort_ts": row[1],
                        "_sort_id": row[0],
                    }
                )

            conn.close()
        except Exception as exc:
            print(f"read message db failed: {msg_db}: {exc}")

    results.sort(key=lambda item: (item.get("_sort_ts", 0), item.get("_sort_id", 0)))
    if limit > 0 and len(results) > limit:
        results = results[-limit:]
    for item in results:
        item.pop("_sort_ts", None)
        item.pop("_sort_id", None)
    return results


def format_dm_messages(contact_name: str, messages: list[dict], date: str | None = None) -> str:
    if not messages:
        return f"{contact_name} has no direct messages for {date or 'today'}."

    lines = [f"=== 私聊对象: {contact_name} | 日期: {date or '今天'} ===\n"]
    for msg in messages:
        prefix = "客户" if msg.get("is_from_customer") else "我方"
        lines.append(f"[{msg['time']}] [{prefix}] {msg['content']}")
    return "\n".join(lines)
