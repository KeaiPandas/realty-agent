import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from models import CustomerProfile


def step_persist_db(wxid: str, messages: list, contact_profile: dict | None = None) -> dict:
    from services.sync.persist import persist_messages
    print(f'[2.5/4] 写入本地数据库...')
    result = persist_messages(wxid, messages, contact_profile)
    print(f'   写入 {result} 条消息')
    return result


def step_persist_profile(wxid: str, profile, contact_profile: dict | None = None) -> None:
    from services.sync.persist import persist_profile
    print(f'[3.5/4] 保存画像到本地数据库...')
    persist_profile(wxid, profile)
    # 同时写入强信号字段
    alias = ((contact_profile or {}).get('alias') or '').strip()
    nickname = ((contact_profile or {}).get('nickname') or (contact_profile or {}).get('display_name') or '').strip()
    updates = {}
    if alias and not alias.startswith('wxid_'):
        updates['wechat_id'] = alias
    if nickname:
        updates['wechat_name'] = nickname  # not a db column, skip
    print(f'   已保存')


def step_decrypt() -> dict:
    print('[1/4] 解密微信数据库...')
    from services.sync.decrypt import decrypt_all_databases

    db_paths = decrypt_all_databases()
    print(f'   解密了 {len(db_paths)} 个数据库')
    return db_paths


def step_list_contacts(db_paths: dict):
    from services.sync.db_layout import get_contact_db
    from services.sync.extract import get_dm_contacts

    contact_db = get_contact_db(db_paths)
    if not contact_db:
        print('错误: 联系人数据库未解密')
        return

    contacts = get_dm_contacts(contact_db)
    print(f'\n共 {len(contacts)} 个私聊联系人:')
    for i, contact in enumerate(contacts[: settings.LIST_CONTACTS_LIMIT], 1):
        alias = contact.get('alias') or ''
        alias_str = f' (微信号: {alias})' if alias else ''
        print(f"  {i}. {contact['nickname']}{alias_str} [{contact['wxid']}]")
    if len(contacts) > settings.LIST_CONTACTS_LIMIT:
        print(f'  ... 还有 {len(contacts) - settings.LIST_CONTACTS_LIMIT} 个')



def step_extract_dm(db_paths: dict, contact_id: str, date: str | None = None) -> list:
    from services.sync.extract import extract_dm_messages

    print(f'[2/4] 提取私聊消息 (联系人: {contact_id})...')
    messages = extract_dm_messages(db_paths, contact_id, date=date)
    print(f'   提取了 {len(messages)} 条消息')
    return messages


async def step_parse(
    chat_content: str,
    existing: dict | None = None,
    contact_id: str | None = None,
    contact_profile: dict | None = None,
) -> CustomerProfile:
    from agents.profile_parser import parse_chat_to_profile

    print('[3/4] AI解析客户画像...')
    profile = await parse_chat_to_profile(
        chat_content,
        existing_profile=existing,
        contact_id=contact_id,
        contact_profile=contact_profile,
    )

    non_null = sum(1 for value in profile.model_dump().values() if value is not None)
    print(f'   提取了 {non_null} 个字段')
    print('\n   关键字段:')
    for key in ['wechat_id', 'wechat_name', 'phone', 'budget_total_wan', 'preferred_area', 'purchase_purpose']:
        value = getattr(profile, key, None)
        if value:
            print(f'     {key}: {value}')
    return profile



def step_sync_dingtalk(profile: CustomerProfile):
    from services.dingtalk_service import sync_profile_to_dingtalk

    if not settings.DINGTALK_BASE_ID or not settings.DINGTALK_TABLE_ID:
        print('\n[4/4] 跳过钉钉同步（未配置 DINGTALK_BASE_ID / DINGTALK_TABLE_ID）')
        return

    print(f"[4/4] 同步到钉钉 (客户: {profile.name or profile.phone or profile.wechat_name or '未知'})...")
    result = sync_profile_to_dingtalk(profile, settings.DINGTALK_BASE_ID, settings.DINGTALK_TABLE_ID)
    print(f"   结果: {result['action']}")
    print(f"   详情: {json.dumps(result, ensure_ascii=False, indent=2)}")



def step_sync_feishu(profile: CustomerProfile):
    from services.feishu_service import sync_profile_to_feishu

    if not settings.FEISHU_BASE_TOKEN or not settings.FEISHU_TABLE_ID:
        print('\n[4/4] 跳过飞书同步（未配置 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID）')
        return

    print(f"[4/4] 同步到飞书 (客户: {profile.name or profile.phone or profile.wechat_name or '未知'})...")
    result = sync_profile_to_feishu(profile, settings.FEISHU_BASE_TOKEN, settings.FEISHU_TABLE_ID)
    print(f"   结果: {result['action']}")
    print(f"   详情: {json.dumps(result, ensure_ascii=False, indent=2)}")
    return result


async def run_pipeline(
    contact_id: str,
    date: str | None = None,
    parse_only: bool = False,
    sync_feishu: bool = False,
):
    db_paths = step_decrypt()

    from services.sync.db_layout import get_contact_db
    from services.sync.extract import format_dm_messages, get_contact_profiles

    messages = step_extract_dm(db_paths, contact_id, date)
    if not messages:
        print('没有找到消息，退出')
        return

    contact_db = get_contact_db(db_paths)
    contact_profile = (get_contact_profiles(contact_db).get(contact_id) if contact_db else None) or {}
    display_name = (
        contact_profile.get('remark')
        or contact_profile.get('nickname')
        or contact_profile.get('alias')
        or contact_id
    )

    # 写入本地数据库
    step_persist_db(contact_id, messages, contact_profile)

    chat_content = format_dm_messages(display_name, messages, date)

    from agents.profile_parser import sanitize_chat_for_llm

    safe_preview = sanitize_chat_for_llm(chat_content)
    print(f'\n--- 聊天记录预览 ---\n{safe_preview[:500]}\n')

    profile = await step_parse(
        chat_content,
        contact_id=contact_id,
        contact_profile=contact_profile,
    )

    alias = (contact_profile.get('alias') or '').strip()
    nickname = (contact_profile.get('nickname') or contact_profile.get('display_name') or '').strip()
    if alias and not alias.startswith('wxid_'):
        profile.wechat_id = alias
    if nickname:
        profile.wechat_name = nickname

    # 保存画像 JSON 文件
    output_path = Path(__file__).parent / settings.DATA_DIR / f'profile_{contact_id}.json'
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\n   画像已保存: {output_path}')

    # 保存画像到本地数据库
    step_persist_profile(contact_id, profile, contact_profile)

    # 飞书同步需要手动触发（--sync 参数）
    if sync_feishu:
        step_sync_feishu(profile)
    else:
        print('\n[4/4] 飞书同步已跳过（使用 --sync 参数或 Web 端按钮触发）')


async def run_parse_file(file_path: str, parse_only: bool = True):
    chat_content = Path(file_path).read_text(encoding='utf-8')
    print(f'读取文件: {file_path} ({len(chat_content)} 字符)\n')

    profile = await step_parse(chat_content)

    output_path = Path(__file__).parent / settings.DATA_DIR / 'profile_parsed.json'
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\n   画像已保存: {output_path}')

    if not parse_only:
        step_sync_feishu(profile)



def main():
    parser = argparse.ArgumentParser(description='Realty Agent CLI')
    parser.add_argument('--list-contacts', action='store_true', help='列出微信私聊联系人')
    parser.add_argument('--contact', type=str, help='联系人 wxid')
    parser.add_argument('--date', type=str, help='指定日期 (YYYY-MM-DD)')
    parser.add_argument('--parse-only', action='store_true', help='只解析不同步飞书')
    parser.add_argument('--sync', action='store_true', help='同步到飞书（默认跳过）')
    parser.add_argument('--parse-file', type=str, help='直接解析聊天文本文件')
    args = parser.parse_args()

    if args.list_contacts:
        db_paths = step_decrypt()
        step_list_contacts(db_paths)
    elif args.parse_file:
        asyncio.run(run_parse_file(args.parse_file, parse_only=args.parse_only))
    elif args.contact:
        asyncio.run(run_pipeline(
            contact_id=args.contact, date=args.date,
            parse_only=args.parse_only, sync_feishu=args.sync,
        ))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
