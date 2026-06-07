// Detail page — customer list for each KPI category
// Fetches real data from API with MOCK fallback

const MOCK_CUSTOMERS = {
  active: [
    { name: '王五', group: '带看中', messages: 45, lastActive: '10分钟前',
      tags: ['带看中', '预算 120 万'], summary: '上周说本周来版纳看房，正在确认行程', risk: 'low' },
    { name: '张三', group: '高意向', messages: 23, lastActive: '2小时前',
      tags: ['高意向', '预算 80 万'], summary: '意向嘎洒，推荐了89㎡三居', risk: 'medium' },
    { name: '李四', group: '新线索', messages: 3, lastActive: '1小时前',
      tags: ['新线索'], summary: '问"有三居吗？"，刚回复推荐', risk: 'low' },
    { name: '赵六', group: '高意向', messages: 15, lastActive: '昨天',
      tags: ['旅居度假', '嘎栋'], summary: '意向嘎栋项目，发送了户型图', risk: 'low' },
    { name: '孙八', group: '高意向', messages: 8, lastActive: '3天前',
      tags: ['自驾看房'], summary: '下周末自驾来版纳，需要安排接待', risk: 'low' },
    { name: '周九', group: '带看中', messages: 12, lastActive: '昨天',
      tags: ['预算 90 万', '曼弄枫'], summary: '看了两套曼弄枫，在比较', risk: 'low' },
    { name: '吴十', group: '高意向', messages: 6, lastActive: '4天前',
      tags: ['投资', '嘎洒'], summary: '纯投资，关注嘎洒项目', risk: 'low' },
    { name: '郑一', group: '新线索', messages: 2, lastActive: '6小时前',
      tags: ['新线索', '养老'], summary: '问养老房，推荐了嘎栋', risk: 'low' },
    { name: '陈二', group: '高意向', messages: 18, lastActive: '昨天',
      tags: ['自住', '预算 150 万'], summary: '想买大户型自住，看中版纳', risk: 'low' },
    { name: '林三', group: '新线索', messages: 1, lastActive: '今天',
      tags: ['新线索'], summary: '刚加微信，问价格', risk: 'low' },
    { name: '黄四', group: '带看中', messages: 34, lastActive: '2天前',
      tags: ['带看中', '嘎洒'], summary: '看过多套嘎洒，在纠结', risk: 'low' },
    { name: '许五', group: '高意向', messages: 9, lastActive: '3天前',
      tags: ['旅居', '预算 70 万'], summary: '想买小户型旅居', risk: 'low' },
  ],
  pending: [
    { name: '李四', group: '高意向', messages: 3, lastActive: '1小时前',
      tags: ['高意向'], summary: '问"有三居吗？"，需回复推荐嘎洒89㎡', risk: 'high' },
    { name: '王五', group: '带看中', messages: 45, lastActive: '10分钟前',
      tags: ['带看中', '沉默12天'], summary: '上周说本周来版纳，确认行程', risk: 'high' },
    { name: '张三', group: '高意向', messages: 23, lastActive: '2小时前',
      tags: ['高意向', '7天未回复'], summary: '意向嘎洒，7天没回复需跟进', risk: 'high' },
    { name: '赵六', group: '高意向', messages: 15, lastActive: '昨天',
      tags: ['旅居度假'], summary: '问嘎栋项目，需发送资料', risk: 'medium' },
    { name: '钱七', group: '沉默', messages: 32, lastActive: '14天前',
      tags: ['沉默预警'], summary: '看过多套后突然断了联系', risk: 'medium' },
  ],
  silent: [
    { name: '钱七', group: '沉默', messages: 32, lastActive: '14天前',
      tags: ['沉默预警', '14天未联系'], summary: '之前看过多套，突然断了联系', risk: 'high' },
    { name: '孙八', group: '高意向', messages: 8, lastActive: '3天前（超过7天）',
      tags: ['自驾看房', '沉默'], summary: '说下周末来，但已过7天没跟进', risk: 'medium' },
    { name: '刘六', group: '未分组', messages: 5, lastActive: '21天前',
      tags: ['沉默', '未分组'], summary: '咨询过一次再没联系', risk: 'medium' },
    { name: '何七', group: '沉默', messages: 2, lastActive: '30天前',
      tags: ['沉默', '失活'], summary: '一个月前加微信，聊两句就没了', risk: 'high' },
    { name: '曹八', group: '未分组', messages: 1, lastActive: '45天前',
      tags: ['失活'], summary: '很久前的线索，可能已放弃', risk: 'high' },
    { name: '严九', group: '沉默', messages: 11, lastActive: '18天前',
      tags: ['沉默预警'], summary: '之前比较积极，突然沉默', risk: 'medium' },
    { name: '邓十', group: '未分组', messages: 4, lastActive: '25天前',
      tags: ['沉默'], summary: '咨询过价格就消失了', risk: 'medium' },
    { name: '魏一', group: '沉默', messages: 7, lastActive: '60天前',
      tags: ['失活'], summary: '两个月没联系，可能已买别家', risk: 'high' },
  ],
  messages: [
    { name: '王五', group: '带看中', messages: 45, lastActive: '10分钟前',
      tags: ['带看中', '预算 120 万'], summary: '活跃度最高，频繁咨询', risk: 'low' },
    { name: '黄四', group: '带看中', messages: 34, lastActive: '2天前',
      tags: ['带看中'], summary: '看过多套，消息量很大', risk: 'low' },
    { name: '钱七', group: '沉默', messages: 32, lastActive: '14天前',
      tags: ['沉默预警'], summary: '之前很活跃，现在沉默了', risk: 'medium' },
    { name: '张三', group: '高意向', messages: 23, lastActive: '2小时前',
      tags: ['高意向', '预算 80 万'], summary: '近期消息较多', risk: 'medium' },
    { name: '陈二', group: '高意向', messages: 18, lastActive: '昨天',
      tags: ['自住', '预算 150 万'], summary: '频繁咨询大户型', risk: 'low' },
    { name: '赵六', group: '高意向', messages: 15, lastActive: '昨天',
      tags: ['旅居度假'], summary: '活跃咨询嘎栋项目', risk: 'low' },
    { name: '周九', group: '带看中', messages: 12, lastActive: '昨天',
      tags: ['预算 90 万'], summary: '看房后持续沟通', risk: 'low' },
    { name: '许五', group: '高意向', messages: 9, lastActive: '3天前',
      tags: ['旅居', '预算 70 万'], summary: '咨询小户型', risk: 'low' },
  ],
};

const CATEGORY_META = {
  active: { title: '活跃客户', sub: '近 7 天有消息', color: 'var(--green)' },
  pending: { title: '待回复', sub: '需要跟进回复', color: 'var(--amber)' },
  silent: { title: '沉默客户', sub: '超过 7 天无联系', color: 'var(--blue)' },
  messages: { title: '新消息', sub: '消息量排行', color: 'var(--gold)' },
};

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function tagClass(tag) {
  const map = {
    '高意向': 'tag-green', '新线索': 'tag-blue', '沉默回归': 'tag-amber',
    '沉默预警': 'tag-amber', '带看中': 'tag-blue', '沉默': 'tag-amber',
    '已成交': 'tag-gold', '14天未联系': 'tag-red', '自驾看房': 'tag-blue',
    '失活': 'tag-red', '未分组': 'tag-muted',
  };
  return map[tag] || 'tag-muted';
}

async function fetchCustomers(cat) {
  try {
    const resp = await fetch(`/api/leads/customers?cat=${encodeURIComponent(cat)}`);
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.customers || null;
  } catch { return null; }
}

function renderCustomerList(customers, cat, meta) {
  document.getElementById('detailTitle').textContent = meta.title;
  document.getElementById('detailSub').textContent = meta.sub;
  document.getElementById('detailCount').textContent = customers.length + ' 人';

  const list = document.getElementById('detailList');
  if (!customers.length) {
    list.innerHTML = '<div class="empty-state">暂无客户</div>';
    return;
  }

  const statLabel = cat === 'messages' ? '消息' : cat === 'active' ? '消息' : cat === 'pending' ? '沉默' : '天';
  list.innerHTML = customers.map(c => `
    <div class="detail-card risk-${c.risk || 'low'}">
      <div class="detail-avatar">${esc((c.name || '?')[0])}</div>
      <div class="detail-info">
        <div class="detail-name">${esc(c.name)}</div>
        <div class="detail-sub">${esc(c.summary)}</div>
        <div class="detail-tags">
          <span class="tag tag-muted">${esc(c.group)}</span>
          ${(c.tags || []).map(t => `<span class="tag ${tagClass(t)}">${esc(t)}</span>`).join('')}
        </div>
      </div>
      <div class="detail-right">
        <div class="detail-stat" style="color:${meta.color}">${c.messages || 0}</div>
        <div class="detail-stat-label">${statLabel} · ${esc(c.lastActive)}</div>
      </div>
    </div>`).join('');
}

export async function initDetail() {
  const params = new URLSearchParams(window.location.search);
  const cat = params.get('cat') || 'active';
  const meta = CATEGORY_META[cat] || CATEGORY_META.active;

  // Try fetching real data first
  const realCustomers = await fetchCustomers(cat);

  if (realCustomers && realCustomers.length > 0) {
    renderCustomerList(realCustomers, cat, meta);
  } else {
    renderCustomerList([], cat, meta);
  }
}
