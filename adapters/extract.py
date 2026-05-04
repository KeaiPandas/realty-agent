"""
从解密后的微信数据库中提取指定群的聊天记录
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def get_group_info(db_path):
    """从 MicroMsg.db 获取群聊信息

    Returns:
        dict: {群名: 群chatroom_id}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 查询所有群聊
    groups = {}
    try:
        cursor.execute("""
            SELECT ChatRoomName, RoomData
            FROM ChatRoom
        """)
        for row in cursor.fetchall():
            chatroom = row["ChatRoomName"]
            if chatroom and chatroom.endswith("@chatroom"):
                # RoomData 中包含群成员信息
                groups[chatroom] = chatroom
    except Exception:
        pass

    # 从 Contact 表获取群名
    try:
        cursor.execute("""
            SELECT UserName, NickName, Alias
            FROM Contact
            WHERE UserName LIKE '%@chatroom'
        """)
        for row in cursor.fetchall():
            username = row["UserName"]
            nickname = row["NickName"]
            if nickname:
                groups[username] = nickname
    except Exception:
        pass

    conn.close()
    return groups


def get_contact_nicknames(db_path):
    """获取所有联系人的昵称映射

    Returns:
        dict: {wxid: 昵称}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    nicknames = {}
    try:
        cursor.execute("SELECT UserName, NickName FROM Contact")
        for row in cursor.fetchall():
            nicknames[row["UserName"]] = row["NickName"]
    except Exception:
        # MicroMsg.db 中可能有不同的表结构
        try:
            cursor.execute("SELECT userName, nickName FROM rcontact")
            for row in cursor.fetchall():
                nicknames[row["userName"]] = row["nickName"]
        except Exception:
            pass

    conn.close()
    return nicknames


def get_chatroom_members(db_path, chatroom_id):
    """获取群成员列表及其昵称"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    members = {}
    try:
        # ChatRoom 表中的 RoomData 包含成员信息
        cursor.execute(
            "SELECT RoomData FROM ChatRoom WHERE ChatRoomName = ?",
            (chatroom_id,),
        )
        row = cursor.fetchone()
        if row and row["RoomData"]:
            # 解析 RoomData (protobuf 格式，简单提取 wxid)
            import re
            data = row["RoomData"]
            # 从二进制数据中提取 wxid
            wxids = re.findall(rb"wxid_[a-zA-Z0-9_]+", data)
            for wxid in wxids:
                members[wxid.decode()] = wxid.decode()
    except Exception:
        pass

    conn.close()
    return members


def extract_messages(db_paths, target_groups, date=None):
    """从消息数据库中提取指定群的聊天记录

    Args:
        db_paths: dict, 解密后的数据库路径
        target_groups: list, 目标群名称列表
        date: str, 目标日期 (YYYY-MM-DD)，默认为今天

    Returns:
        dict: {群名: [{time, sender, content, type}, ...]}
    """
    if date is None:
        target_date = datetime.now()
    else:
        target_date = datetime.strptime(date, "%Y-%m-%d")

    start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp())
    end_ts = int(
        (target_date + timedelta(days=1))
        .replace(hour=0, minute=0, second=0)
        .timestamp()
    )

    # 获取群聊信息
    micromsg_path = db_paths.get("MicroMsg")
    if not micromsg_path:
        raise RuntimeError("MicroMsg.db 未解密")

    all_groups = get_group_info(micromsg_path)
    nicknames = get_contact_nicknames(micromsg_path)

    # 反向映射：群名 -> chatroom_id
    name_to_id = {}
    for chatroom_id, display_name in all_groups.items():
        name_to_id[display_name] = chatroom_id

    # 匹配目标群
    target_ids = {}
    for group_name in target_groups:
        if group_name in name_to_id:
            target_ids[name_to_id[group_name]] = group_name
        else:
            print(f"  警告: 未找到群「{group_name}」")
            # 模糊匹配
            for display_name, chatroom_id in name_to_id.items():
                if group_name in display_name or display_name in group_name:
                    target_ids[chatroom_id] = display_name
                    print(f"  → 匹配到: {display_name}")
                    break

    if not target_ids:
        print("  可用的群聊列表:")
        for name in sorted(set(all_groups.values())):
            print(f"    - {name}")
        return {}

    # 从所有消息数据库中提取消息
    msg_dbs = []
    for name in ["ChatMsg"] + [f"MSG{i}" for i in range(100)]:
        if name in db_paths:
            msg_dbs.append(db_paths[name])

    results = {group_name: [] for group_name in target_ids.values()}

    # 消息类型映射
    MSG_TYPES = {
        1: "文本",
        3: "图片",
        34: "语音",
        43: "视频",
        47: "表情",
        49: "链接/文件",
        10000: "系统消息",
    }

    for msg_db in msg_dbs:
        if not Path(msg_db).exists():
            continue

        try:
            conn = sqlite3.connect(msg_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 尝试不同的表名
            tables = []
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            for row in cursor.fetchall():
                tables.append(row["name"])

            # 找到消息表
            msg_table = None
            for t in tables:
                if t.upper() == "MSG":
                    msg_table = t
                    break

            if not msg_table:
                conn.close()
                continue

            for chatroom_id, group_name in target_ids.items():
                cursor.execute(
                    f"""
                    SELECT localId, MsgSvrID, StrTalker, CreateTime,
                           Type, SubType, CreateTime, StrContent,
                           BytesExtra, CompressContent
                    FROM {msg_table}
                    WHERE StrTalker = ?
                      AND CreateTime >= ?
                      AND CreateTime < ?
                    ORDER BY CreateTime ASC
                    """,
                    (chatroom_id, start_ts, end_ts),
                )

                for row in cursor.fetchall():
                    msg_type = row["Type"]
                    content = row["StrContent"] or ""

                    # 只处理文本消息和系统消息
                    if msg_type not in (1, 10000):
                        continue

                    # 提取发送者
                    sender_wxid = ""
                    if msg_type == 1 and ":\n" in content:
                        # 群消息格式: "wxid_xxx:\n实际内容"
                        parts = content.split(":\n", 1)
                        sender_wxid = parts[0]
                        content = parts[1] if len(parts) > 1 else content

                    sender = nicknames.get(sender_wxid, sender_wxid)

                    msg_time = datetime.fromtimestamp(row["CreateTime"])

                    results[group_name].append(
                        {
                            "time": msg_time.strftime("%H:%M"),
                            "sender": sender,
                            "content": content.strip(),
                            "type": MSG_TYPES.get(msg_type, f"类型{msg_type}"),
                        }
                    )

            conn.close()
        except Exception as e:
            print(f"  读取 {msg_db} 出错: {e}")

    return results


def format_messages(group_name, messages, date=None):
    """将消息格式化为文本，供 AI 处理

    Args:
        group_name: 群名
        messages: 消息列表
        date: 日期字符串

    Returns:
        str: 格式化后的文本
    """
    if not messages:
        return f"群「{group_name}」在 {date or '今天'} 没有消息。"

    lines = [f"=== 群: {group_name} | 日期: {date or '今天'} ===\n"]

    for msg in messages:
        if msg["type"] == "系统消息":
            lines.append(f"[{msg['time']}] [系统] {msg['content']}")
        else:
            lines.append(f"[{msg['time']}] {msg['sender']}: {msg['content']}")

    return "\n".join(lines)


def get_dm_contacts(db_path: str) -> list[dict]:
    """获取所有私聊联系人（排除群聊、公众号、系统号）"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    contacts = []
    try:
        cursor.execute("""
            SELECT UserName, NickName, Alias
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
                })
        except Exception:
            pass

    conn.close()
    return contacts


def extract_dm_messages(
    db_paths: dict, contact_id: str, date: str | None = None, limit: int = 200
) -> list[dict]:
    """提取指定联系人的私聊消息

    与群聊的关键区别：DM消息的StrContent直接是消息内容，无需split(":\n")
    """
    if date is None:
        target_date = datetime.now()
    else:
        target_date = datetime.strptime(date, "%Y-%m-%d")

    start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp())
    end_ts = int(
        (target_date + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()
    )

    micromsg_path = db_paths.get("MicroMsg")
    nicknames = get_contact_nicknames(micromsg_path) if micromsg_path else {}

    msg_dbs = []
    for name in ["ChatMsg"] + [f"MSG{i}" for i in range(100)]:
        if name in db_paths:
            msg_dbs.append(db_paths[name])

    MSG_TYPES = {
        1: "文本",
        3: "图片",
        34: "语音",
        43: "视频",
        49: "链接/文件",
        10000: "系统消息",
    }

    results = []

    for msg_db in msg_dbs:
        if not Path(msg_db).exists():
            continue

        try:
            conn = sqlite3.connect(msg_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            tables = []
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for row in cursor.fetchall():
                tables.append(row["name"])

            msg_table = None
            for t in tables:
                if t.upper() == "MSG":
                    msg_table = t
                    break

            if not msg_table:
                conn.close()
                continue

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

            for row in cursor.fetchall():
                content = row["StrContent"] or ""
                msg_time = datetime.fromtimestamp(row["CreateTime"])

                # 判断方向：如果昵称匹配则是对方发的，否则是自己发的
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


if __name__ == "__main__":
    import yaml

    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    wechat_dir = Path(config["wechat"]["data_dir"])
    decrypted_dir = wechat_dir / "decrypted"

    db_paths = {"MicroMsg": str(decrypted_dir / "MicroMsg.db")}
    for f in sorted(decrypted_dir.glob("MSG*.db")):
        db_paths[f.stem] = str(f)
    if (decrypted_dir / "ChatMsg.db").exists():
        db_paths["ChatMsg"] = str(decrypted_dir / "ChatMsg.db")

    # 默认列出私聊联系人
    import sys
    if "--list-contacts" in sys.argv:
        contacts = get_dm_contacts(db_paths["MicroMsg"])
        print(f"共 {len(contacts)} 个私聊联系人：")
        for c in contacts[:30]:
            print(f"  {c['nickname']} ({c['wxid']})")
    elif "--dm" in sys.argv:
        idx = sys.argv.index("--dm")
        contact_id = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
        dm_date = None
        if "--date" in sys.argv:
            dm_date = sys.argv[sys.argv.index("--date") + 1]
        if contact_id:
            msgs = extract_dm_messages(db_paths, contact_id, date=dm_date)
            print(format_dm_messages(contact_id, msgs, date=dm_date))
