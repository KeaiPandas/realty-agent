"""WeChat 数据库版本检测与路径解析

抽象 3.x 和 4.x 的数据库目录结构差异，提供统一的路径访问接口。
3.x: Msg/MicroMsg.db, Msg/ChatMsg.db, Msg/Multi/MSG*.db
4.x: db_storage/contact/contact.db, db_storage/message/message_0.db, ...
"""
from pathlib import Path


def detect_wechat_version() -> str:
    """检测微信版本（基于进程名）"""
    import psutil
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name", "")
        if name == "Weixin.exe":
            return "4.x"
        if name == "WeChat.exe":
            return "3.x"
    raise RuntimeError("未检测到微信进程，请先登录微信")


def get_db_layout(wx_dir: Path, version: str) -> dict[str, Path]:
    """根据版本返回所有数据库文件的 {逻辑名: 物理路径} 映射"""
    wx_dir = Path(wx_dir)
    db_files: dict[str, Path] = {}

    if version == "4.x":
        storage = wx_dir / "db_storage"
        if not storage.exists():
            raise RuntimeError(f"4.x 数据目录不存在: {storage}")

        # 联系人
        contact = storage / "contact" / "contact.db"
        if contact.exists():
            db_files["contact"] = contact

        # 消息（message_0.db, message_1.db, ...）
        msg_dir = storage / "message"
        if msg_dir.exists():
            for f in sorted(msg_dir.glob("message_*.db")):
                if f.stem != "message_fts":
                    db_files[f.stem] = f

        # 会话
        session = storage / "session" / "session.db"
        if session.exists():
            db_files["session"] = session

        # 其他有用数据库
        general = storage / "general" / "general.db"
        if general.exists():
            db_files["general"] = general

    else:
        # 3.x
        msg_dir = wx_dir / "Msg"
        if not msg_dir.exists():
            raise RuntimeError(f"3.x 数据目录不存在: {msg_dir}")

        for name in ("MicroMsg", "ChatMsg", "ChatRoomUser", "Misc"):
            p = msg_dir / f"{name}.db"
            if p.exists():
                db_files[name] = p

        multi_dir = msg_dir / "Multi"
        if multi_dir.exists():
            for f in sorted(multi_dir.glob("MSG*.db")):
                db_files[f.stem] = f

    return db_files


def get_contact_db(db_paths: dict) -> str | None:
    """从解密后的数据库路径字典中获取联系人数据库路径（兼容 3.x/4.x 命名）"""
    for key in ("contact", "MicroMsg"):
        path = db_paths.get(key)
        if path:
            return str(path)
    return None


def get_message_dbs(db_paths: dict) -> list[str]:
    """从解密后的数据库路径字典中获取所有消息数据库路径"""
    result = []
    # 4.x: message_0, message_1, ...
    # 3.x: ChatMsg, MSG0, MSG1, ...
    for key in sorted(db_paths.keys()):
        if key.startswith("message_") or key in ("ChatMsg",) or key.startswith("MSG"):
            path = db_paths[key]
            if path:
                result.append(str(path))
    return result
