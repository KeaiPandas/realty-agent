import asyncio
import json
import re
from pathlib import Path

import yaml
from langchain_openai import ChatOpenAI

from config import settings
from models import CustomerProfile


SUMMARY_FIELDS = {
    'name', 'age', 'hometown', 'current_city', 'employer_type', 'family_members',
    'marital_status', 'children_status', 'elder_care', 'douyin_name', 'source_channel',
    'entry_point', 'keyword', 'visited_banna', 'first_visit_date', 'current_visit_date',
    'planned_settle_date', 'stay_duration_days', 'visit_purpose', 'annual_stay_months',
    'purchase_purpose', 'purchase_reason', 'preferred_area', 'property_type',
    'purchase_count', 'layout', 'area_sqm', 'floor_preference', 'decoration_standard',
    'budget_total_wan', 'price_per_sqm', 'planned_time', 'orientation',
    'view_preference', 'facilities_needed', 'community_env', 'decoration_style',
    'living_env', 'climate_preference', 'lifestyle', 'travel_mode', 'extra_hobbies',
    'payment_method', 'down_payment', 'monthly_payment', 'existing_properties',
    'credit_status', 'fund_status', 'followup_content', 'demand_update',
    'concern_points', 'interested_properties', 'rejected_reason', 'next_followup_date',
    'followup_stage', 'tags', 'personality', 'decision_maker', 'trust_level',
    'deal_probability', 'followup_strategy', 'special_notes',
}

LOCAL_FIELDS = {
    'phone', 'wechat_id', 'wechat_name', 'first_contact_date',
    'first_followup_date', 'latest_followup_date',
}

JSON_INSTRUCTION = (
    'Return a JSON object only. '
    'Do not use markdown code fences. '
    'Include only fields with concrete values and omit nulls.'
)

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r'(?i)\b((?:feishu|lark|openai|llm)[a-z0-9_:-]*?(?:token|key|secret|table_id|base_id)|password)\b\s*[:=]\s*\S+')
]
PHONE_PATTERN = re.compile(r'(?<!\d)(1[3-9]\d{9})(?!\d)')
TIMESTAMP_PATTERN = re.compile(r'\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]')



CHINESE_NUMBER_MAP = {
    '?': 1,
    '?': 2,
    '?': 2,
    '?': 3,
    '?': 4,
    '?': 5,
    '?': 6,
    '?': 7,
    '?': 8,
    '?': 9,
    '?': 10,
}

def load_prompts() -> dict:
    prompts_path = Path(__file__).parent.parent / settings.PROMPTS_FILE
    with open(prompts_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def sanitize_chat_for_llm(chat_content: str) -> str:
    sanitized_lines: list[str] = []
    for raw_line in chat_content.splitlines():
        line = raw_line
        if '[API sender probe]' in line:
            continue
        for pattern in SENSITIVE_VALUE_PATTERNS:
            line = pattern.sub('[REDACTED_SECRET]', line)
        sanitized_lines.append(line)
    return '\n'.join(sanitized_lines).strip()


def extract_local_profile_fields(
    chat_content: str,
    contact_id: str | None = None,
    contact_profile: dict | None = None,
) -> dict:
    local_profile: dict[str, object] = {}

    if contact_profile:
        alias = (contact_profile.get('alias') or '').strip()
        nickname = (contact_profile.get('nickname') or contact_profile.get('display_name') or '').strip()
        if alias and not alias.startswith('wxid_'):
            local_profile['wechat_id'] = alias
        if nickname:
            local_profile['wechat_name'] = nickname

    phone_match = PHONE_PATTERN.search(chat_content)
    if phone_match:
        local_profile['phone'] = phone_match.group(1)

    message_dates = TIMESTAMP_PATTERN.findall(chat_content)
    if message_dates:
        local_profile['first_contact_date'] = message_dates[0]
        local_profile['first_followup_date'] = message_dates[0]
        local_profile['latest_followup_date'] = message_dates[-1]

    if contact_id:
        local_profile['_wxid'] = contact_id

    return local_profile


def _filter_fields(data: dict, allowed_fields: set[str]) -> dict:
    return {
        key: value
        for key, value in (data or {}).items()
        if key in allowed_fields and value not in (None, '', [], {})
    }


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith('```'):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == '```':
        return '\n'.join(lines[1:-1]).strip()
    return '\n'.join(lines[1:]).strip()


def _first_number(value):
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    match = re.search(r'\d+(?:\.\d+)?', value)
    if match:
        number = float(match.group(0))
        return int(number) if number.is_integer() else number
    for char in value:
        if char in CHINESE_NUMBER_MAP:
            return CHINESE_NUMBER_MAP[char]
    if '??' in value:
        return 2
    return None


def _normalize_scalar_fields(data: dict) -> dict:
    for key in ('phone', 'existing_properties', 'wechat_name', 'douyin_name', 'wechat_id'):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            data[key] = str(data[key])

    for key in ('visited_banna', 'credit_status', 'fund_status', 'marital_status', 'payment_method', 'decision_maker'):
        if key in data and isinstance(data[key], bool):
            data[key] = '?' if data[key] else '?'

    int_fields = {'age', 'family_members', 'stay_duration_days', 'purchase_count', 'annual_stay_months'}
    float_fields = {'area_sqm', 'budget_total_wan', 'price_per_sqm', 'down_payment', 'monthly_payment'}

    for key in int_fields | float_fields:
        if key not in data or data[key] is None:
            continue
        number = _first_number(data[key])
        if number is None:
            if isinstance(data[key], str):
                data.pop(key, None)
            continue
        if key in int_fields:
            data[key] = int(number)
        else:
            data[key] = float(number)
            if data[key] == int(data[key]):
                data[key] = int(data[key])
    return data


async def _invoke_json_agent(system_prompt: str, user_prompt: str) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                timeout=120,
                max_retries=1,
            )
            response = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        {'role': 'system', 'content': f'{system_prompt}\n\n{JSON_INSTRUCTION}'},
                        {'role': 'user', 'content': user_prompt},
                    ]
                ),
                timeout=180,
            )
            content = _strip_code_fence(response.content)
            return json.loads(content) if content else {}
        except Exception as exc:
            last_error = exc
            if attempt >= 2:
                raise
            await asyncio.sleep(4 * (attempt + 1))
    raise last_error


async def parse_chat_to_profile(
    chat_content: str,
    existing_profile: dict | None = None,
    contact_id: str | None = None,
    contact_profile: dict | None = None,
) -> CustomerProfile:
    prompts = load_prompts()
    sanitized_chat = sanitize_chat_for_llm(chat_content)
    local_profile = extract_local_profile_fields(
        chat_content=chat_content,
        contact_id=contact_id,
        contact_profile=contact_profile,
    )

    summary_user = prompts['profile_summary_agent']['user_template'].format(
        chat_content=sanitized_chat,
        existing_profile=json.dumps(
            _filter_fields(existing_profile or {}, SUMMARY_FIELDS),
            ensure_ascii=False,
            indent=2,
        ) if existing_profile else 'NONE',
        allowed_fields=', '.join(sorted(SUMMARY_FIELDS)),
    )
    summary_profile = _filter_fields(
        await _invoke_json_agent(prompts['profile_summary_agent']['system'], summary_user),
        SUMMARY_FIELDS,
    )

    final_profile = {
        **summary_profile,
        **_filter_fields(local_profile, LOCAL_FIELDS),
    }
    if not final_profile:
        raise ValueError('LLM returned an empty customer profile')

    final_profile = _normalize_scalar_fields(final_profile)

    return CustomerProfile(**final_profile)


def parse_chat_to_profile_sync(
    chat_content: str,
    existing_profile: dict | None = None,
    contact_id: str | None = None,
    contact_profile: dict | None = None,
) -> CustomerProfile:
    return asyncio.run(
        parse_chat_to_profile(
            chat_content,
            existing_profile=existing_profile,
            contact_id=contact_id,
            contact_profile=contact_profile,
        )
    )


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python profile_parser.py <chat_file.txt>')
        raise SystemExit(1)

    chat_file = Path(sys.argv[1])
    if not chat_file.exists():
        print(f'File not found: {chat_file}')
        raise SystemExit(1)

    chat_content = chat_file.read_text(encoding='utf-8')
    profile = parse_chat_to_profile_sync(chat_content)
    print(json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2))
