"""微信数据目录自动检测 + 持久化"""
import os
from pathlib import Path

import psutil
import yaml


def detect_wechat_data_dir(version: str) -> str | None:
    if version == "4.x" or version == "auto":
        result = detect_v4_data_dir()
        if result:
            return result
    if version == "3.x" or version == "auto":
        return detect_v3_data_dir()
    return None


def detect_v4_data_dir() -> str | None:
    candidates: list[Path] = []
    weixin_procs = [p for p in psutil.process_iter(["name", "pid"])
                    if p.info["name"] == "Weixin.exe"]
    if not weixin_procs:
        return None

    for proc in weixin_procs:
        # Strategy 1: open files (most reliable)
        try:
            for f in proc.open_files():
                candidate = _extract_wxid_from_path(Path(f.path))
                if candidate:
                    candidates.append(candidate)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        # Strategy 2: cwd
        try:
            cwd = Path(proc.cwd())
            candidate = _find_wxid_dir(cwd)
            if candidate:
                candidates.append(candidate)
        except (psutil.AccessDenied, psutil.NoSuchProcess, FileNotFoundError):
            pass

    if not candidates:
        return None
    return str(_pick_best_candidate(candidates))


def detect_v3_data_dir() -> str | None:
    try:
        from adapters.decrypt import _get_wx_info_v3
        wx_info = _get_wx_info_v3()
        if isinstance(wx_info, list) and wx_info:
            return wx_info[0].get("wx_dir", "") or None
    except Exception:
        pass
    return None


def persist_data_dir(path: str) -> None:
    from config import settings, CONFIG_DIR
    yaml_path = CONFIG_DIR / "wechat.yaml"
    data = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data["data_dir"] = path
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    settings.WECHAT_DATA_DIR = path


# ── Internal helpers ──

def _find_wxid_dir(directory: Path) -> Path | None:
    """Check directory and its children for wxid_*/db_storage/ pattern."""
    if _is_wxid_dir(directory):
        return directory
    if not directory.is_dir():
        return None
    for child in directory.iterdir():
        if child.is_dir() and _is_wxid_dir(child):
            return child
    return None


def _is_wxid_dir(p: Path) -> bool:
    return p.name.startswith("wxid_") and (p / "db_storage").is_dir()


def _extract_wxid_from_path(fpath: Path) -> Path | None:
    """Extract wxid dir from a file path containing db_storage."""
    parts = fpath.parts
    for i, part in enumerate(parts):
        if part == "db_storage" and i >= 2:
            wxid_dir = Path(*parts[:i])
            if _is_wxid_dir(wxid_dir):
                return wxid_dir
    return None


def _pick_best_candidate(candidates: list[Path]) -> Path:
    """Pick the wxid dir with the most recently modified contact.db."""
    best = candidates[0]
    best_mtime = 0
    for d in candidates:
        contact_db = d / "db_storage" / "contact" / "contact.db"
        if contact_db.exists():
            mtime = contact_db.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = d
    return best
