"""SQLite 持久化层 — 客户、消息、待办、简报

所有业务数据存入 data/realty.db，替代分散的 JSON 文件和内存状态。
"""
import json
import sqlite3
import time
from pathlib import Path

from config import settings

DB_PATH = Path(settings.DATA_DIR) / "realty.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    wxid TEXT PRIMARY KEY,
    nickname TEXT DEFAULT '',
    alias TEXT DEFAULT '',
    remark TEXT DEFAULT '',
    phone TEXT,
    wechat_id TEXT,
    stage TEXT DEFAULT 'initial',
    profile_json TEXT,
    risk_level TEXT DEFAULT 'low',
    risk_updated_at REAL,
    first_seen_at REAL,
    last_message_at REAL,
    last_reply_at REAL,
    message_count INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wxid TEXT NOT NULL,
    content TEXT,
    is_from_customer INTEGER DEFAULT 1,
    timestamp REAL,
    reply TEXT,
    reply_status TEXT DEFAULT '',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wxid TEXT,
    type TEXT,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    source TEXT,
    ai_suggestion TEXT,
    created_at REAL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS briefings (
    date TEXT PRIMARY KEY,
    content TEXT,
    generated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_customers_risk ON customers(risk_level);
CREATE INDEX IF NOT EXISTS idx_customers_stage ON customers(stage);
CREATE INDEX IF NOT EXISTS idx_messages_wxid ON messages(wxid);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status, priority);
"""


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（启用 WAL 模式 + 外键）"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.close()


# ── 客户 CRUD ──

def upsert_customer(wxid: str, **kwargs) -> dict:
    """插入或更新客户，返回更新后的记录"""
    conn = get_conn()
    now = time.time()

    existing = conn.execute(
        "SELECT wxid FROM customers WHERE wxid = ?", (wxid,)
    ).fetchone()

    if existing:
        # 构建 UPDATE 语句
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k == "profile_json" and isinstance(v, dict):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = ?")
            vals.append(v)
        sets.append("updated_at = ?")
        vals.append(now)
        vals.append(wxid)
        conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE wxid = ?", vals)
    else:
        cols = ["wxid", "created_at", "updated_at", "first_seen_at"]
        vals = [wxid, now, now, now]
        for k, v in kwargs.items():
            if k == "profile_json" and isinstance(v, dict):
                v = json.dumps(v, ensure_ascii=False)
            cols.append(k)
            vals.append(v)
        placeholders = ", ".join(["?"] * len(cols))
        conn.execute(
            f"INSERT INTO customers ({', '.join(cols)}) VALUES ({placeholders})", vals
        )

    conn.commit()
    row = conn.execute("SELECT * FROM customers WHERE wxid = ?", (wxid,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_customer(wxid: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM customers WHERE wxid = ?", (wxid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_customers() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM customers ORDER BY last_message_at DESC NULLS LAST"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_customers_by_risk(risk_level: str | None = None) -> list[dict]:
    conn = get_conn()
    if risk_level:
        rows = conn.execute(
            "SELECT * FROM customers WHERE risk_level = ? ORDER BY last_message_at DESC NULLS LAST",
            (risk_level,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM customers ORDER BY CASE risk_level "
            "WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "last_message_at DESC NULLS LAST"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kpi_stats() -> dict:
    """获取 KPI 统计数据"""
    conn = get_conn()
    now = time.time()
    h72 = now - 72 * 3600
    h24 = now - 24 * 3600
    d7 = now - 7 * 86400
    today_start = now - (now % 86400)  # midnight today

    active = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE last_message_at > ?", (h72,)
    ).fetchone()[0]

    new_messages = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE is_from_customer = 1 AND timestamp > ?",
        (today_start,),
    ).fetchone()[0]

    pending_reply = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE last_message_at > ? "
        "AND (last_reply_at IS NULL OR last_reply_at < last_message_at - ?)",
        (d7, h24),
    ).fetchone()[0]

    silent = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE last_message_at < ? "
        "AND message_count > 0",
        (d7,),
    ).fetchone()[0]

    conn.close()
    return {
        "active_customers": active,
        "new_messages_today": new_messages,
        "pending_reply": pending_reply,
        "silent_customers": silent,
    }


# ── 消息 CRUD ──

def insert_message(wxid: str, content: str, is_from_customer: bool = True,
                   timestamp: float | None = None, reply: str = "",
                   reply_status: str = "") -> int:
    conn = get_conn()
    now = time.time()
    ts = timestamp or now
    cursor = conn.execute(
        "INSERT INTO messages (wxid, content, is_from_customer, timestamp, reply, "
        "reply_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (wxid, content, int(is_from_customer), ts, reply, reply_status, now),
    )
    # 更新客户表
    if is_from_customer:
        conn.execute(
            "UPDATE customers SET last_message_at = ?, message_count = message_count + 1, "
            "updated_at = ? WHERE wxid = ?",
            (ts, now, wxid),
        )
    else:
        conn.execute(
            "UPDATE customers SET last_reply_at = ?, updated_at = ? WHERE wxid = ?",
            (ts, now, wxid),
        )
    conn.commit()
    msg_id = cursor.lastrowid
    conn.close()
    return msg_id


def get_messages(wxid: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE wxid = ? ORDER BY timestamp DESC LIMIT ?",
        (wxid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_message_stats() -> dict:
    """今日消息时间分布"""
    conn = get_conn()
    now = time.time()
    today_start = now - (now % 86400)

    # 按时段统计
    morning = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE is_from_customer = 1 "
        "AND timestamp > ? AND (timestamp % 86400) BETWEEN 21600 AND 43200",
        (today_start,),
    ).fetchone()[0]  # 6:00-12:00 UTC → 14:00-20:00 CST

    afternoon = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE is_from_customer = 1 "
        "AND timestamp > ? AND (timestamp % 86400) BETWEEN 43200 AND 64800",
        (today_start,),
    ).fetchone()[0]  # 12:00-18:00 UTC

    evening = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE is_from_customer = 1 "
        "AND timestamp > ? AND ((timestamp % 86400) >= 64800 OR (timestamp % 86400) < 21600)",
        (today_start,),
    ).fetchone()[0]  # 18:00-6:00

    # 阶段分布
    stage_rows = conn.execute(
        "SELECT stage, COUNT(*) as cnt FROM customers GROUP BY stage"
    ).fetchall()

    # 7天趋势
    trend = []
    for i in range(6, -1, -1):
        day_start = now - (now % 86400) - i * 86400
        day_end = day_start + 86400
        cnt = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE is_from_customer = 1 "
            "AND timestamp >= ? AND timestamp < ?",
            (day_start, day_end),
        ).fetchone()[0]
        from datetime import datetime
        trend.append({
            "date": datetime.fromtimestamp(day_start).strftime("%m-%d"),
            "messages": cnt,
        })

    conn.close()
    return {
        "message_distribution": {
            "morning": morning,
            "afternoon": afternoon,
            "evening": evening,
        },
        "stage_distribution": {r["stage"]: r["cnt"] for r in stage_rows},
        "daily_trend": trend,
    }


# ── 待办 CRUD ──

def create_action(wxid: str, action_type: str, description: str,
                  priority: str = "medium", source: str = "",
                  ai_suggestion: str = "", due_date: str = "") -> int:
    conn = get_conn()
    now = time.time()
    cursor = conn.execute(
        "INSERT INTO actions (wxid, type, description, priority, status, source, "
        "ai_suggestion, due_date, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
        (wxid, action_type, description, priority, source, ai_suggestion, due_date, now),
    )
    conn.commit()
    action_id = cursor.lastrowid
    conn.close()
    return action_id


def get_pending_actions(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT a.*, c.nickname FROM actions a "
        "LEFT JOIN customers c ON a.wxid = c.wxid "
        "WHERE a.status = 'pending' "
        "ORDER BY CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "a.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_action(action_id: int, status: str) -> bool:
    conn = get_conn()
    now = time.time()
    cursor = conn.execute(
        "UPDATE actions SET status = ?, completed_at = ? WHERE id = ?",
        (status, now if status in ("done", "skipped") else None, action_id),
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


# ── 简报 ──

def save_briefing(date: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO briefings (date, content, generated_at) VALUES (?, ?, ?)",
        (date, content, time.time()),
    )
    conn.commit()
    conn.close()


def get_briefing(date: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM briefings WHERE date = ?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None
