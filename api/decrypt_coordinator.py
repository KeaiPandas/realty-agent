"""数据库解密协调 — 内存缓存 → 磁盘缓存 → 重新解密"""
from pathlib import Path

from adapters.db_layout import get_contact_db
from config import settings

_decrypted_db_paths: dict = {}


def do_decrypt() -> dict:
    from adapters.decrypt import decrypt_all_databases
    return decrypt_all_databases()


def find_existing_decrypted() -> dict[str, str] | None:
    try:
        from adapters.decrypt import _resolve_version
        from adapters.db_layout import get_db_layout
        version = _resolve_version()
        wechat_dir = settings.WECHAT_DATA_DIR
        if not wechat_dir:
            return None
        wechat_dir = Path(wechat_dir)
        dec_dir = wechat_dir / "decrypted"
        if not dec_dir.exists():
            return None
        db_layout = get_db_layout(wechat_dir, version)
        existing = {}
        for name, src_path in db_layout.items():
            dec_path = dec_dir / f"{name}.db"
            if not dec_path.exists() or dec_path.stat().st_size == 0:
                return None
            # 源文件比解密文件新则缓存失效
            if Path(src_path).exists() and Path(src_path).stat().st_mtime > dec_path.stat().st_mtime:
                return None
            existing[name] = str(dec_path)
        return existing if get_contact_db(existing) else None
    except Exception:
        return None


def ensure_decrypted() -> dict:
    global _decrypted_db_paths
    if _decrypted_db_paths and get_contact_db(_decrypted_db_paths):
        return _decrypted_db_paths
    existing = find_existing_decrypted()
    if existing:
        _decrypted_db_paths = existing
        return existing
    result = do_decrypt()
    _decrypted_db_paths = result
    return result


def get_decrypted_paths() -> dict:
    return _decrypted_db_paths
