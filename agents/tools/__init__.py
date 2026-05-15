from agents.tools.wechat_tools import (
    get_wechat_info,
    decrypt_wechat_db,
    search_wechat_contact,
    extract_dm_messages,
)
from agents.tools.profile_tools import (
    parse_chat_to_profile,
    save_profile,
    load_profile,
)
from agents.tools.sync_tools import (
    sync_profile_to_feishu,
    query_feishu_by_wechat,
    query_feishu_by_phone,
    sync_profile_to_dingtalk,
)

ALL_TOOLS = [
    get_wechat_info,
    decrypt_wechat_db,
    search_wechat_contact,
    extract_dm_messages,
    parse_chat_to_profile,
    save_profile,
    load_profile,
    sync_profile_to_feishu,
    query_feishu_by_wechat,
    query_feishu_by_phone,
    sync_profile_to_dingtalk,
]


def get_tools():
    return ALL_TOOLS
