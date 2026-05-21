"""
AI客服A岗 MVP — 端到端管道
用法:
  python main.py --list-contacts                    # 列出微信私聊联系人
  python main.py --contact <wxid>                   # 提取+解析+同步
  python main.py --contact <wxid> --date 2026-05-03 # 指定日期
  python main.py --contact <wxid> --parse-only      # 只解析不同步飞书
  python main.py --parse-file <chat.txt>            # 直接解析指定文件
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from models import CustomerProfile


def step_decrypt() -> dict:
    """Step 1: 解密微信数据库"""
    print("[1/4] 解密微信数据库...")
    from services.sync.decrypt import decrypt_all_databases

    db_paths = decrypt_all_databases()
    print(f"   解密了 {len(db_paths)} 个数据库")
    return db_paths


def step_list_contacts(db_paths: dict):
    """Step 2: 列出私聊联系人"""
    from services.sync.extract import get_dm_contacts
    from services.sync.db_layout import get_contact_db

    contact_db = get_contact_db(db_paths)
    if not contact_db:
        print("错误: 联系人数据库未解密")
        return

    contacts = get_dm_contacts(contact_db)
    print(f"\n共 {len(contacts)} 个私聊联系人：")
    for i, c in enumerate(contacts[:settings.LIST_CONTACTS_LIMIT], 1):
        alias_str = f" (微信号: {c['alias']})" if c["alias"] else ""
        print(f"  {i}. {c['nickname']}{alias_str} [{c['wxid']}]")
    if len(contacts) > settings.LIST_CONTACTS_LIMIT:
        print(f"  ... 还有 {len(contacts) - settings.LIST_CONTACTS_LIMIT} 个")


def step_extract_dm(db_paths: dict, contact_id: str, date: str | None = None) -> list:
    """Step 2: 提取DM私聊消息"""
    from services.sync.extract import extract_dm_messages

    print(f"[2/4] 提取私聊消息 (联系人: {contact_id})...")
    messages = extract_dm_messages(db_paths, contact_id, date=date)
    print(f"   提取了 {len(messages)} 条消息")
    return messages


async def step_parse(chat_content: str, existing: dict = None) -> CustomerProfile:
    """Step 3: AI解析画像"""
    from agents.profile_parser import parse_chat_to_profile

    print("[3/4] AI解析客户画像...")
    profile = await parse_chat_to_profile(chat_content, existing_profile=existing)

    non_null = sum(1 for v in profile.model_dump().values() if v is not None)
    print(f"   提取了 {non_null} 个字段")

    print("\n   关键字段：")
    for key in ["name", "phone", "budget_total_wan", "preferred_area", "purchase_purpose", "followup_stage"]:
        val = getattr(profile, key, None)
        if val:
            print(f"     {key}: {val}")

    return profile


def step_sync_dingtalk(profile: CustomerProfile):
    """Step 4: 同步钉钉"""
    from services.dingtalk_service import sync_profile_to_dingtalk

    if not settings.DINGTALK_BASE_ID or not settings.DINGTALK_TABLE_ID:
        print("\n[4/4] 跳过钉钉同步（未配置 DINGTALK_BASE_ID / DINGTALK_TABLE_ID）")
        print("   请设置环境变量或在 .env 文件中配置")
        return

    print(f"[4/4] 同步到钉钉 (客户: {profile.name or profile.phone or '未知'})...")
    result = sync_profile_to_dingtalk(
        profile, settings.DINGTALK_BASE_ID, settings.DINGTALK_TABLE_ID
    )
    print(f"   结果: {result['action']}")
    print(f"   详情: {json.dumps(result, ensure_ascii=False, indent=2)}")


def step_sync_feishu(profile: CustomerProfile):
    """Step 4 (alt): 同步飞书"""
    from services.feishu_service import sync_profile_to_feishu

    if not settings.FEISHU_BASE_TOKEN or not settings.FEISHU_TABLE_ID:
        print("\n[4/4] 跳过飞书同步（未配置 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID）")
        return

    print(f"[4/4] 同步到飞书 (客户: {profile.name or profile.phone or '未知'})...")
    result = sync_profile_to_feishu(
        profile, settings.FEISHU_BASE_TOKEN, settings.FEISHU_TABLE_ID
    )
    print(f"   结果: {result['action']}")
    print(f"   详情: {json.dumps(result, ensure_ascii=False, indent=2)}")
    return result


async def run_pipeline(
    contact_id: str,
    date: str | None = None,
    parse_only: bool = False,
):
    """运行完整管道"""
    # Step 1: 解密
    db_paths = step_decrypt()

    # Step 2: 提取DM消息
    from services.sync.extract import format_dm_messages

    messages = step_extract_dm(db_paths, contact_id, date)
    if not messages:
        print("没有找到消息，退出")
        return

    chat_content = format_dm_messages(contact_id, messages, date)
    print(f"\n--- 聊天记录预览 ---\n{chat_content[:500]}\n")

    # Step 3: AI解析
    profile = await step_parse(chat_content)

    # 保存解析结果到本地
    output_path = Path(__file__).parent / settings.DATA_DIR / f"profile_{contact_id}.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n   画像已保存: {output_path}")

    # Step 4: 同步飞书
    if not parse_only:
        step_sync_feishu(profile)
    else:
        print("\n[4/4] --parse-only 模式，跳过同步")


async def run_parse_file(file_path: str, parse_only: bool = True):
    """直接解析指定文件"""
    chat_content = Path(file_path).read_text(encoding="utf-8")
    print(f"读取文件: {file_path} ({len(chat_content)} 字符)\n")

    profile = await step_parse(chat_content)

    output_path = Path(__file__).parent / settings.DATA_DIR / f"profile_parsed.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(
        json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n   画像已保存: {output_path}")

    if not parse_only:
        step_sync_feishu(profile)


def main():
    parser = argparse.ArgumentParser(description="AI客服A岗 MVP")
    parser.add_argument("--list-contacts", action="store_true", help="列出微信私聊联系人")
    parser.add_argument("--contact", type=str, help="联系人wxid")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--parse-only", action="store_true", help="只解析不同步飞书")
    parser.add_argument("--parse-file", type=str, help="直接解析指定的聊天记录文件")
    args = parser.parse_args()

    if args.list_contacts:
        db_paths = step_decrypt()
        step_list_contacts(db_paths)

    elif args.parse_file:
        asyncio.run(run_parse_file(args.parse_file, parse_only=args.parse_only))

    elif args.contact:
        asyncio.run(run_pipeline(
            contact_id=args.contact,
            date=args.date,
            parse_only=args.parse_only,
        ))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
