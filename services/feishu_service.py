import json
import re
import subprocess

from config import settings
from models import CustomerProfile, FEISHU_FIELD_MAP


DATETIME_FIELDS = {
    '首次留资时间',
    '本次来版纳时间',
    '购房计划时间',
    '首次跟进时间',
    '本次跟进时间',
}


def _run_lark_cli(args: list[str], timeout: int = 0) -> dict:
    cmd = [settings.LARK_CLI_PATH] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout or settings.CLI_TIMEOUT,
        encoding='utf-8',
    )
    if result.returncode != 0:
        raise RuntimeError(f'lark-cli error: {result.stderr.strip()}')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {'raw': result.stdout}



def _profile_to_feishu_cells(profile: CustomerProfile) -> dict:
    data = profile.model_dump(exclude_none=True)
    cells = {}
    for cn_name, py_name in FEISHU_FIELD_MAP.items():
        value = data.get(py_name)
        if value is None:
            continue
        text = str(value)
        if cn_name in DATETIME_FIELDS and not re.match(r'\d{4}-\d{2}-\d{2}', text):
            continue
        cells[cn_name] = text
    return cells



def query_record_by_wechat_id(wechat_id: str, base_token: str, table_id: str) -> dict | None:
    try:
        result = _run_lark_cli([
            'base', '+record-search',
            '--base-token', base_token,
            '--table-id', table_id,
            '--json', json.dumps({
                'keyword': wechat_id,
                'search_fields': ['微信号'],
                'limit': 1,
            }, ensure_ascii=False),
            '--format', 'json',
        ])
        data = result.get('data', {})
        record_ids = data.get('record_id_list', [])
        rows = data.get('data', [])
        if record_ids and rows:
            return {'record_id': record_ids[0], 'data': rows[0]}
    except Exception:
        pass
    return None



def query_record_by_phone(phone: str, base_token: str, table_id: str) -> dict | None:
    try:
        result = _run_lark_cli([
            'base', '+record-search',
            '--base-token', base_token,
            '--table-id', table_id,
            '--json', json.dumps({
                'keyword': phone,
                'search_fields': ['联系方式'],
                'limit': 1,
            }, ensure_ascii=False),
            '--format', 'json',
        ])
        data = result.get('data', {})
        record_ids = data.get('record_id_list', [])
        rows = data.get('data', [])
        if record_ids and rows:
            return {'record_id': record_ids[0], 'data': rows[0]}
    except Exception:
        pass
    return None



def create_record(profile: CustomerProfile, base_token: str, table_id: str) -> dict:
    cells = _profile_to_feishu_cells(profile)
    return _run_lark_cli([
        'base', '+record-upsert',
        '--base-token', base_token,
        '--table-id', table_id,
        '--json', json.dumps(cells, ensure_ascii=False),
    ])



def update_record(record_id: str, profile: CustomerProfile, base_token: str, table_id: str) -> dict:
    cells = _profile_to_feishu_cells(profile)
    return _run_lark_cli([
        'base', '+record-upsert',
        '--base-token', base_token,
        '--table-id', table_id,
        '--record-id', record_id,
        '--json', json.dumps(cells, ensure_ascii=False),
    ])



def sync_profile_to_feishu(profile: CustomerProfile, base_token: str, table_id: str) -> dict:
    wechat_id = profile.wechat_id
    if wechat_id and str(wechat_id).startswith('wxid_'):
        wechat_id = None

    if wechat_id:
        existing = query_record_by_wechat_id(wechat_id, base_token, table_id)
        if existing:
            record_id = existing['record_id']
            result = update_record(record_id, profile, base_token, table_id)
            return {'action': 'updated', 'record_id': record_id, 'result': result}

    if profile.phone:
        existing = query_record_by_phone(profile.phone, base_token, table_id)
        if existing:
            record_id = existing['record_id']
            result = update_record(record_id, profile, base_token, table_id)
            return {'action': 'updated', 'record_id': record_id, 'result': result}

    result = create_record(profile, base_token, table_id)
    return {'action': 'created', 'result': result}


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python feishu_service.py <profile.json> <base_token> <table_id>')
        raise SystemExit(1)

    profile_file = sys.argv[1]
    base_token = sys.argv[2] if len(sys.argv) > 2 else ''
    table_id = sys.argv[3] if len(sys.argv) > 3 else ''

    with open(profile_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    profile = CustomerProfile(**data)
    result = sync_profile_to_feishu(profile, base_token, table_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
