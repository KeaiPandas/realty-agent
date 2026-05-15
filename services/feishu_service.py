import json
import subprocess

from config import settings
from models import CustomerProfile, FEISHU_FIELD_MAP


def _run_lark_cli(args: list[str], timeout: int = 0) -> dict:
    cmd = [settings.LARK_CLI_PATH] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout or settings.CLI_TIMEOUT,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(f"lark-cli error: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout}


# 飞书datetime类型字段，值必须是 YYYY-MM-DD 或 YYYY-MM-DD HH:mm:ss 格式
_DATETIME_FIELDS = {
    "首次留资时间", "本次来版纳时间", "购房计划时间",
    "首次跟进时间", "本次跟进时间",
}

import re as _re

def _profile_to_feishu_cells(profile: CustomerProfile) -> dict:
    data = profile.model_dump(exclude_none=True)
    cells = {}
    for cn_name, py_name in FEISHU_FIELD_MAP.items():
        if py_name in data and data[py_name] is not None:
            val = str(data[py_name])
            # datetime字段严格校验：非日期格式直接跳过
            if cn_name in _DATETIME_FIELDS:
                if not _re.match(r"\d{4}-\d{2}-\d{2}", val):
                    continue
            cells[cn_name] = val
    return cells


def query_record_by_wechat_id(wechat_id: str, base_token: str, table_id: str) -> dict | None:
    """按微信号查询飞书记录（唯一键去重）"""
    try:
        result = _run_lark_cli([
            "base", "+record-search",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps({
                "keyword": wechat_id,
                "search_fields": ["微信号"],
                "limit": 1,
            }),
            "--format", "json",
        ])
        data = result.get("data", {})
        record_ids = data.get("record_id_list", [])
        rows = data.get("data", [])
        if record_ids and rows:
            return {"record_id": record_ids[0], "data": rows[0]}
    except Exception:
        pass
    return None


def query_record_by_phone(phone: str, base_token: str, table_id: str) -> dict | None:
    """按手机号查询飞书记录"""
    try:
        result = _run_lark_cli([
            "base", "+record-search",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps({
                "keyword": phone,
                "search_fields": ["联系方式"],
                "limit": 1,
            }),
            "--format", "json",
        ])
        data = result.get("data", {})
        record_ids = data.get("record_id_list", [])
        rows = data.get("data", [])
        if record_ids and rows:
            return {"record_id": record_ids[0], "data": rows[0]}
    except Exception:
        pass
    return None


def create_record(profile: CustomerProfile, base_token: str, table_id: str) -> dict:
    cells = _profile_to_feishu_cells(profile)
    return _run_lark_cli([
        "base", "+record-upsert",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(cells),
    ])


def update_record(
    record_id: str, profile: CustomerProfile, base_token: str, table_id: str
) -> dict:
    cells = _profile_to_feishu_cells(profile)
    return _run_lark_cli([
        "base", "+record-upsert",
        "--base-token", base_token,
        "--table-id", table_id,
        "--record-id", record_id,
        "--json", json.dumps(cells),
    ])


def sync_profile_to_feishu(
    profile: CustomerProfile, base_token: str, table_id: str
) -> dict:
    """同步客户画像到飞书（按微信号唯一键去重：有则更新，无则创建）"""
    wechat_id = profile.wechat_id

    if wechat_id:
        # 优先按微信号去重
        existing = query_record_by_wechat_id(wechat_id, base_token, table_id)
        if existing:
            record_id = existing["record_id"]
            result = update_record(record_id, profile, base_token, table_id)
            return {"action": "updated", "record_id": record_id, "result": result}

    if profile.phone:
        # 没有微信号时按手机号去重
        existing = query_record_by_phone(profile.phone, base_token, table_id)
        if existing:
            record_id = existing["record_id"]
            result = update_record(record_id, profile, base_token, table_id)
            return {"action": "updated", "record_id": record_id, "result": result}

    # 全新记录
    result = create_record(profile, base_token, table_id)
    return {"action": "created", "result": result}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python feishu_service.py <profile.json> <base_token> <table_id>")
        sys.exit(1)

    profile_file = sys.argv[1]
    base_token = sys.argv[2] if len(sys.argv) > 2 else ""
    table_id = sys.argv[3] if len(sys.argv) > 3 else ""

    with open(profile_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    profile = CustomerProfile(**data)
    print(f"同步客户: {profile.name or profile.phone or '未知'}")

    result = sync_profile_to_feishu(profile, base_token, table_id)
    print(f"结果: {result['action']}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
