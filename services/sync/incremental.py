"""增量同步游标管理

参考 WechatExporter 的流式游标模式。
持久化每个联系人最后同步位置，避免重启后重复处理。
"""
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class SyncCursor:
    contact_id: str
    db_name: str
    last_local_id: int = 0
    last_timestamp: float = 0.0


class CursorStore:
    """持久化的同步游标存储"""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_cursors (
                contact_id TEXT NOT NULL,
                db_name TEXT NOT NULL,
                last_local_id INTEGER DEFAULT 0,
                last_timestamp REAL DEFAULT 0.0,
                PRIMARY KEY (contact_id, db_name)
            )
        """)
        conn.commit()
        conn.close()

    def get(self, contact_id: str, db_name: str = "") -> SyncCursor:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT last_local_id, last_timestamp FROM sync_cursors "
            "WHERE contact_id = ? AND db_name = ?",
            (contact_id, db_name),
        ).fetchone()
        conn.close()
        if row:
            return SyncCursor(contact_id, db_name, row[0], row[1])
        return SyncCursor(contact_id, db_name)

    def update(self, cursor: SyncCursor):
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO sync_cursors (contact_id, db_name, last_local_id, last_timestamp) "
            "VALUES (?, ?, ?, ?)",
            (cursor.contact_id, cursor.db_name, cursor.last_local_id, cursor.last_timestamp),
        )
        conn.commit()
        conn.close()

    def get_all(self) -> list[SyncCursor]:
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            "SELECT contact_id, db_name, last_local_id, last_timestamp FROM sync_cursors"
        ).fetchall()
        conn.close()
        return [SyncCursor(r[0], r[1], r[2], r[3]) for r in rows]
