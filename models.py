from typing import Optional
from pydantic import BaseModel, Field


class CustomerProfile(BaseModel):
    """客户核心画像"""

    # ── 系统字段 ──
    customer_id: Optional[str] = Field(None, description="用户唯一ID，如USR0001")
    phone: Optional[str] = Field(None, description="手机号（11位唯一标识）")
    wechat_id: Optional[str] = Field(None, description="微信号（飞书唯一键）")

    # ── ①基本信息 ──
    name: Optional[str] = Field(None, description="客户姓名")
    gender: Optional[str] = Field(None, description="性别：男/女")
    age: Optional[int] = Field(None, description="年龄（数字）")
    hometown: Optional[str] = Field(None, description="籍贯")
    current_city: Optional[str] = Field(None, description="现在居住城市")
    employer_type: Optional[str] = Field(None, description="工作单位性质")
    family_members: Optional[int] = Field(None, description="家庭常住人口数")
    marital_status: Optional[str] = Field(None, description="婚姻状况：已婚/未婚/离异")
    children_status: Optional[str] = Field(None, description="子女状况，如1个孩子12岁")
    elder_care: Optional[str] = Field(None, description="赡养老人情况")
    wechat_name: Optional[str] = Field(None, description="微信名称")
    douyin_name: Optional[str] = Field(None, description="抖音昵称")

    # ── ②客户来源信息 ──
    source_channel: Optional[str] = Field(None, description="自媒体获客渠道：抖音/视频号/小红书")
    entry_point: Optional[str] = Field(None, description="引流入口：短视频/直播/文章")
    first_contact_date: Optional[str] = Field(None, description="首次留资时间，YYYY-MM-DD")
    keyword: Optional[str] = Field(None, description="引流关键词")

    # ── ③旅居信息 ──
    visited_banna: Optional[str] = Field(None, description="是否来过目标城市：是/否")
    first_visit_date: Optional[str] = Field(None, description="首次来版纳时间")
    current_visit_date: Optional[str] = Field(None, description="本次来版纳时间")
    planned_settle_date: Optional[str] = Field(None, description="计划定居版纳时间")
    stay_duration_days: Optional[int] = Field(None, description="本次在版纳停留天数")
    visit_purpose: Optional[str] = Field(None, description="来版纳主要目的，如旅居、养老")
    annual_stay_months: Optional[int] = Field(None, description="每年计划来版纳居住月数")

    # ── ④核心购房需求 ──
    purchase_purpose: Optional[str] = Field(None, description="购房核心目的：旅居度假/养老/投资/刚需/改善")
    purchase_reason: Optional[str] = Field(None, description="购房首要原因")
    preferred_area: Optional[str] = Field(None, description="意向购房区域，如嘎栋、曼弄枫")
    property_type: Optional[str] = Field(None, description="意向房源类型：别墅/洋房/高层/公寓")
    purchase_count: Optional[int] = Field(None, description="购房套数")
    layout: Optional[str] = Field(None, description="意向户型：1室/2室/3室")
    area_sqm: Optional[float] = Field(None, description="意向建筑面积（平方米）")
    floor_preference: Optional[str] = Field(None, description="意向楼层偏好")
    decoration_standard: Optional[str] = Field(None, description="意向装修标准：毛坯/简装/精装")
    budget_total_wan: Optional[float] = Field(None, description="购房意向总价（万元）")
    price_per_sqm: Optional[float] = Field(None, description="购房单价范围（元/平）")
    planned_time: Optional[str] = Field(None, description="购房计划时间，YYYY-MM-DD或如3-6个月")

    # ── ⑤个人购房偏好 ──
    orientation: Optional[str] = Field(None, description="朝向偏好，如南向、南北通透")
    view_preference: Optional[str] = Field(None, description="景观偏好，如山景、园景")
    facilities_needed: Optional[str] = Field(None, description="生活配套需求")
    community_env: Optional[str] = Field(None, description="小区环境偏好")
    decoration_style: Optional[str] = Field(None, description="装修风格偏好")
    living_env: Optional[str] = Field(None, description="居住环境偏好，如环境好郊区")
    climate_preference: Optional[str] = Field(None, description="气候环境需求")
    lifestyle: Optional[str] = Field(None, description="生活习惯")
    travel_mode: Optional[str] = Field(None, description="出行方式偏好")
    extra_hobbies: Optional[str] = Field(None, description="额外喜好")

    # ── ⑥购房预算资质 ──
    payment_method: Optional[str] = Field(None, description="付款方式：全款/商贷/公积金/组合贷")
    down_payment: Optional[float] = Field(None, description="首付预算（万元）")
    monthly_payment: Optional[float] = Field(None, description="贷款月供范围（元）")
    existing_properties: Optional[str] = Field(None, description="名下房产数量")
    credit_status: Optional[str] = Field(None, description="征信情况：良好/一般/有逾期")
    fund_status: Optional[str] = Field(None, description="资金情况：已到位/筹集中")

    # ── ⑦跟进沟通 ──
    first_followup_date: Optional[str] = Field(None, description="首次跟进时间")
    latest_followup_date: Optional[str] = Field(None, description="本次跟进时间")
    followup_content: Optional[str] = Field(None, description="跟进核心内容")
    demand_update: Optional[str] = Field(None, description="客户核心诉求更新")
    concern_points: Optional[str] = Field(None, description="客户顾虑点")
    interested_properties: Optional[str] = Field(None, description="意向房源记录")
    rejected_reason: Optional[str] = Field(None, description="拒绝房源原因")
    next_followup_date: Optional[str] = Field(None, description="预计下次跟进时间")

    # ── ⑧跟进阶段 ──
    followup_stage: Optional[str] = Field(None, description="跟进阶段：初步咨询/意向筛选/带看洽谈/成交/流失待定")

    # ── ⑨画像总结 ──
    tags: Optional[str] = Field(None, description="客户核心标签，逗号分隔")
    personality: Optional[str] = Field(None, description="客户性格特征")
    decision_maker: Optional[str] = Field(None, description="真正决策人")
    trust_level: Optional[str] = Field(None, description="客户信任度：高/中/低")
    deal_probability: Optional[str] = Field(None, description="成交概率预判：高/中/低")
    followup_strategy: Optional[str] = Field(None, description="个性化跟进策略")
    special_notes: Optional[str] = Field(None, description="客户特殊需求备注")


# 钉钉表单字段名 → Pydantic字段名 映射
DINGTALK_FIELD_MAP = {
    "用户ID": "customer_id",
    "联系方式": "phone",
    "客户姓名": "name",
    "性别": "gender",
    "年龄区间": "age",
    "籍贯": "hometown",
    "现在居住城市": "current_city",
    "工作单位性质": "employer_type",
    "家庭常住人口": "family_members",
    "婚姻状况": "marital_status",
    "子女状况": "children_status",
    "赡养老人情况": "elder_care",
    "微信名称": "wechat_name",
    "抖音昵称": "douyin_name",
    "自媒体获客渠道": "source_channel",
    "引流入口": "entry_point",
    "首次留资时间": "first_contact_date",
    "引流关键词": "keyword",
    "是否来过西双版纳": "visited_banna",
    "首次来版纳时间": "first_visit_date",
    "本次来版纳时间": "current_visit_date",
    "计划定居版纳时间": "planned_settle_date",
    "本次在版纳停留时间": "stay_duration_days",
    "来版纳主要目的": "visit_purpose",
    "每年计划来版纳居住时间": "annual_stay_months",
    "购房核心目的": "purchase_purpose",
    "购房首要原因": "purchase_reason",
    "意向购房区域": "preferred_area",
    "意向房源类型": "property_type",
    "购房套数": "purchase_count",
    "意向户型": "layout",
    "意向建筑面积": "area_sqm",
    "意向楼层偏好": "floor_preference",
    "意向装修标准": "decoration_standard",
    "购房意向总价": "budget_total_wan",
    "购房单价范围": "price_per_sqm",
    "购房计划时间": "planned_time",
    "房源朝向偏好": "orientation",
    "景观偏好": "view_preference",
    "生活配套需求": "facilities_needed",
    "小区环境偏好": "community_env",
    "装修风格偏好": "decoration_style",
    "居住环境偏好": "living_env",
    "气候环境需求": "climate_preference",
    "生活习惯": "lifestyle",
    "出行方式偏好": "travel_mode",
    "额外喜好": "extra_hobbies",
    "付款方式": "payment_method",
    "首付预算": "down_payment",
    "贷款月供范围": "monthly_payment",
    "名下房产数量": "existing_properties",
    "征信情况": "credit_status",
    "资金情况": "fund_status",
    "首次跟进时间": "first_followup_date",
    "本次跟进时间": "latest_followup_date",
    "跟进核心内容": "followup_content",
    "客户核心诉求更新": "demand_update",
    "客户顾虑点": "concern_points",
    "意向房源记录": "interested_properties",
    "拒绝房源原因": "rejected_reason",
    "预计下次跟进时间": "next_followup_date",
    "客户跟进阶段": "followup_stage",
    "客户核心标签": "tags",
    "客户性格特征": "personality",
    "真正决策人": "decision_maker",
    "客户信任度": "trust_level",
    "成交概率预判": "deal_probability",
    "个性化跟进策略": "followup_strategy",
    "客户特殊需求备注": "special_notes",
}

# 飞书多维表格列名 → Pydantic字段名 映射（与飞书表严格对齐）
# 跳过: 用户编号(auto_number), 创建人/时间/修改人/时间(系统字段)
FEISHU_FIELD_MAP = {
    "微信号": "wechat_id",
    "联系方式": "phone",
    "微信名称": "wechat_name",
    "客户姓名": "name",
    "年龄": "age",
    "籍贯": "hometown",
    "工作单位性质": "employer_type",
    "家庭常住人口": "family_members",
    "婚姻状况": "marital_status",
    "首次留资时间": "first_contact_date",
    "本次来版纳时间": "current_visit_date",
    "本次在版纳停留天数": "stay_duration_days",
    "购房核心目的": "purchase_purpose",
    "购房首要原因": "purchase_reason",
    "意向购房区域": "preferred_area",
    "意向户型": "layout",
    "意向装修标准": "decoration_standard",
    "购房意向总价": "budget_total_wan",
    "购房单价范围": "price_per_sqm",
    "购房计划时间": "planned_time",
    "房源朝向偏好": "orientation",
    "生活配套需求": "facilities_needed",
    "出行方式偏好": "travel_mode",
    "额外喜好": "extra_hobbies",
    "付款方式": "payment_method",
    "首付预算": "down_payment",
    "贷款月供范围": "monthly_payment",
    "征信情况": "credit_status",
    "资金情况": "fund_status",
    "首次跟进时间": "first_followup_date",
    "本次跟进时间": "latest_followup_date",
    "跟进核心内容": "followup_content",
    "客户顾虑点": "concern_points",
    "拒绝房源原因": "rejected_reason",
    "真正决策人": "decision_maker",
    "客户特殊需求备注": "special_notes",
}
