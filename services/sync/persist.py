"""将微信同步提取的数据写入本地 SQLite DB（services/db.py 的 realty.db）"""
import json
import time

from services.db import get_conn, upsert_customer


def persist_contacts(contacts: list[dict]) -> int:
    """批量写入联系人到 customers 表。返回写入/更新数量。"""
    if not contacts:
        return 0
    count = 0
    for c in contacts:
        wxid = c.get("wxid") or c.get("userName", "")
        if not wxid:
            continue
        kwargs = {}
        if c.get("nickname"):
            kwargs["nickname"] = c["nickname"]
        if c.get("alias"):
            kwargs["alias"] = c["alias"]
        if c.get("remark"):
            kwargs["remark"] = c["remark"]
        # alias 作为 wechat_id（微信号）
        alias = (c.get("alias") or "").strip()
        if alias and not alias.startswith("wxid_"):
            kwargs["wechat_id"] = alias
        upsert_customer(wxid, **kwargs)
        count += 1
    return count


def persist_messages(wxid: str, messages: list[dict], contact_profile: dict | None = None) -> int:
    """批量写入消息到 messages 表，按 timestamp 去重。返回插入数量。"""
    if not messages:
        return 0

    conn = get_conn()

    # 获取该联系人已有消息的最大 timestamp，用于去重
    row = conn.execute(
        "SELECT MAX(timestamp) FROM messages WHERE wxid = ?", (wxid,)
    ).fetchone()
    max_ts = row[0] if row and row[0] else 0

    now = time.time()
    inserted = 0
    for msg in messages:
        ts = msg.get("timestamp") or msg.get("createTime", 0)
        # timestamp 可能是秒或毫秒
        if ts > 1e12:
            ts = ts / 1000
        if ts <= max_ts:
            continue  # 跳过已存在的消息

        content = msg.get("content", "")
        is_from_customer = int(msg.get("is_from_customer", msg.get("isSend", 1) == 0))

        conn.execute(
            "INSERT INTO messages (wxid, content, is_from_customer, timestamp, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (wxid, content, is_from_customer, ts, now),
        )
        inserted += 1

    # 更新客户表的 last_message_at 和 message_count
    if inserted > 0:
        conn.execute(
            "UPDATE customers SET message_count = message_count + ?, updated_at = ? "
            "WHERE wxid = ?",
            (inserted, now, wxid),
        )
        # 找到最新的客户消息时间
        latest = conn.execute(
            "SELECT MAX(timestamp) FROM messages WHERE wxid = ? AND is_from_customer = 1",
            (wxid,),
        ).fetchone()[0]
        if latest:
            conn.execute(
                "UPDATE customers SET last_message_at = ? WHERE wxid = ?",
                (latest, wxid),
            )

    conn.commit()
    conn.close()
    return inserted


def persist_profile(wxid: str, profile) -> None:
    """将 AI 解析的 CustomerProfile 写入 customers 表的 profile_json 和 stage 字段。"""
    profile_dict = profile.model_dump(exclude_none=True)
    kwargs = {"profile_json": json.dumps(profile_dict, ensure_ascii=False)}

    # 从画像中提取 stage
    stage = getattr(profile, "followup_stage", None)
    if stage:
        kwargs["stage"] = stage

    # 从画像中提取强信号字段
    phone = getattr(profile, "phone", None)
    if phone:
        kwargs["phone"] = phone

    wechat_id = getattr(profile, "wechat_id", None)
    if wechat_id:
        kwargs["wechat_id"] = wechat_id

    name = getattr(profile, "name", None)
    if name:
        kwargs["remark"] = name

    upsert_customer(wxid, **kwargs)


def persist_all_for_contact(wxid: str, messages: list[dict], contact_profile: dict | None = None) -> dict:
    """一次性写入某个联系人的消息。返回统计。"""
    msg_count = persist_messages(wxid, messages, contact_profile)
    return {"wxid": wxid, "messages_inserted": msg_count}
