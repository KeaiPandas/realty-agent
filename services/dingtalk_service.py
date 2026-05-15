import json
import subprocess

from config import settings
from models import CustomerProfile, DINGTALK_FIELD_MAP


def _run_dws(args: list[str], timeout: int = 0) -> dict:
    """调用 dws CLI 并返回JSON结果"""
    cmd = [settings.DWS_CLI_PATH] + args + ["--format", "json"]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout or settings.CLI_TIMEOUT,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(f"dws CLI error: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout}


def _profile_to_dingtalk_cells(profile: CustomerProfile) -> dict:
    """将 CustomerProfile 转换为钉钉表单的 cells 格式 {列名: 值}"""
    data = profile.model_dump(exclude_none=True)
    cells = {}
    for cn_name, py_name in DINGTALK_FIELD_MAP.items():
        if py_name in data and data[py_name] is not None:
            cells[cn_name] = str(data[py_name])
    return cells


def query_record_by_phone(phone: str, base_id: str, table_id: str) -> dict | None:
    """按手机号查询钉钉记录，返回已有记录或None"""
    try:
        result = _run_dws([
            "aitable", "record", "query",
            "--base-id", base_id,
            "--table-id", table_id,
            "--filter", json.dumps({"联系方式": phone}),
        ])
        records = result.get("records", result.get("items", []))
        if records and len(records) > 0:
            return records[0]
    except Exception:
        pass
    return None


def create_record(profile: CustomerProfile, base_id: str, table_id: str) -> dict:
    """在钉钉AI表创建新记录"""
    cells = _profile_to_dingtalk_cells(profile)
    return _run_dws([
        "aitable", "record", "create",
        "--base-id", base_id,
        "--table-id", table_id,
        "--records", json.dumps([{"cells": cells}]),
        "-y",
    ])


def update_record(
    record_id: str, profile: CustomerProfile, base_id: str, table_id: str
) -> dict:
    """更新钉钉AI表已有记录"""
    cells = _profile_to_dingtalk_cells(profile)
    return _run_dws([
        "aitable", "record", "update",
        "--base-id", base_id,
        "--table-id", table_id,
        "--record-id", record_id,
        "--cells", json.dumps(cells),
        "-y",
    ])


def sync_profile_to_dingtalk(
    profile: CustomerProfile, base_id: str, table_id: str
) -> dict:
    """同步客户画像到钉钉（自动判断创建/更新）

    Returns:
        {"action": "created"|"updated", "record_id": ...}
    """
    phone = profile.phone
    if not phone:
        # 没有手机号直接创建
        result = create_record(profile, base_id, table_id)
        return {"action": "created", "result": result}

    existing = query_record_by_phone(phone, base_id, table_id)

    if existing:
        record_id = existing.get("recordId", existing.get("id", ""))
        result = update_record(record_id, profile, base_id, table_id)
        return {"action": "updated", "record_id": record_id, "result": result}
    else:
        result = create_record(profile, base_id, table_id)
        return {"action": "created", "result": result}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python dingtalk_service.py <profile.json> <base_id> <table_id>")
        sys.exit(1)

    profile_file = sys.argv[1]
    base_id = sys.argv[2] if len(sys.argv) > 2 else ""
    table_id = sys.argv[3] if len(sys.argv) > 3 else ""

    with open(profile_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = CustomerProfile(**data)
    print(f"同步客户: {profile.name or profile.phone or '未知'}")

    result = sync_profile_to_dingtalk(profile, base_id, table_id)
    print(f"结果: {result['action']}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
