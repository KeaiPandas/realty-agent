// Dashboard page logic — fetches real API data with MOCK fallback
// Uses group-manager.js for sidebar groups

const MOCK = {
  lastSync: '2026-06-07 14:30',
  kpi: {
    active: 12,
    new_messages: 38,
    pending_reply: 5,
    silent: 8,
  },
  briefing: {
    date: '2026-06-07',
    text: '今日新增 <strong>3 条高意向线索</strong>。<strong>张三</strong>预算 80 万意向嘎洒，7 天未回复，建议今天带看。<strong>李四</strong>问"有三居吗"，推荐嘎洒 89㎡ 三居。<strong>王五</strong>上周说本周来版纳，提醒确认行程。沉默客户 <strong>8 人</strong>，其中 3 人超过 14 天未联系。',
  },
  notable: [
    { id: 1, name: '张三', group: 'high_intent', tags: ['高意向', '沉默回归'],
      summary: '预算 80 万意向嘎洒，7 天未回复', time: '2h前' },
    { id: 2, name: '王五', group: 'showing', tags: ['带看中', '预算 120 万'],
      summary: '上周说本周来版纳看房，确认行程', time: '5h前' },
    { id: 3, name: '赵六', group: 'high_intent', tags: ['新线索', '预算 60 万'],
      summary: '问嘎栋项目，意向旅居度假', time: '昨天' },
    { id: 4, name: '钱七', group: 'silent', tags: ['沉默预警', '14天未联系'],
      summary: '之前看过多套，突然断了联系', time: '3天前' },
    { id: 5, name: '孙八', group: 'high_intent', tags: ['高意向', '自驾看房'],
      summary: '下周末自驾来版纳，需要安排接待', time: '昨天' },
  ],
  actions: [
    { id: 1, name: '李四', group: 'high_intent', type: 'reply', priority: 'high',
      desc: '"有三居吗？" → 推荐嘎洒 89㎡ 三居', done: false },
    { id: 2, name: '王五', group: 'showing', type: 'activate', priority: 'high',
      desc: '沉默 12 天，确认本周是否来版纳', done: false },
    { id: 3, name: '张三', group: 'high_intent', type: 'followup', priority: 'high',
      desc: '7 天未回复，发送带看邀请', done: false },
    { id: 4, name: '赵六', group: 'high_intent', type: 'confirm', priority: 'medium',
      desc: '发送嘎栋项目资料 + 户型图', done: false },
    { id: 5, name: '钱七', group: 'silent', type: 'activate', priority: 'medium',
      desc: '14 天未联系，发问候消息', done: false },
  ],
  sources: [
    { name: '王五', group: 'showing', messages: 45, lastActive: '10分钟前',
      tags: ['带看中', '预算 120 万'] },
    { name: '张三', group: 'high_intent', messages: 23, lastActive: '2小时前',
      tags: ['高意向', '预算 80 万'] },
    { name: '李四', group: 'high_intent', messages: 3, lastActive: '1小时前',
      tags: ['新线索'] },
    { name: '赵六', group: 'high_intent', messages: 15, lastActive: '昨天',
      tags: ['旅居度假', '嘎栋'] },
    { name: '孙八', group: 'high_intent', messages: 8, lastActive: '3天前',
      tags: ['自驾看房'] },
    { name: '钱七', group: 'silent', messages: 32, lastActive: '14天前',
      tags: ['沉默'] },
  ],
};

const state = {
  activeGroup: 'all',
  actions: [],
  kpi: null,
  briefing: null,
  notable: null,
  sources: null,
};

// ── Utils ──

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
  };
  return map[tag] || 'tag-muted';
}

function filterByGroup(items) {
  if (state.activeGroup === 'all') return items;
  return items.filter(item => item.group === state.activeGroup);
}

// ── API Fetchers ──

async function fetchHealth() {
  try {
    const resp = await fetch('/api/health');
    if (!resp.ok) return null;
    return resp.json();
  } catch { return null; }
}

function renderEnvBar(health) {
  const map = {
    wechat_process: 'envWechat',
    wechat_db: 'envDb',
    feishu: 'envFeishu',
    llm: 'envLlm',
  };
  if (!health || !health.checks) {
    Object.values(map).forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.className = 'env-pill error';
      el.querySelector('.env-tip').textContent = '无法连接后端';
    });
    return;
  }
  for (const [key, elId] of Object.entries(map)) {
    const el = document.getElementById(elId);
    if (!el) continue;
    const check = health.checks[key];
    const tip = el.querySelector('.env-tip');
    el.className = 'env-pill ' + (check.status === 'ok' ? 'ok' : 'error');
    tip.textContent = check.message || '';
  }
}

async function fetchKPI() {
  try {
    const resp = await fetch('/api/leads/stats');
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.kpi || null;
  } catch { return null; }
}

async function fetchBriefing() {
  try {
    const resp = await fetch('/api/leads/briefing');
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data.summary) {
      return { date: data.date, text: data.summary };
    }
    return null;
  } catch { return null; }
}

async function fetchNotable() {
  try {
    const resp = await fetch('/api/leads/risk');
    if (!resp.ok) return [];
    const data = await resp.json();
    const leads = data.leads || [];
    // 取 top high/medium risk 转为 notable 格式
    const riskLeads = leads.filter(l => l.risk_level === 'high' || l.risk_level === 'medium').slice(0, 5);
    if (!riskLeads.length) return [];
    return riskLeads.map((l, i) => {
      const profile = l.key_profile || {};
      const tags = [];
      if (l.stage === 'intent') tags.push('高意向');
      if (l.stage === 'showing') tags.push('带看中');
      if (l.silence_days > 7) tags.push('沉默回归');
      if (profile.budget) tags.push(`预算 ${profile.budget}万`);
      return {
        id: i + 1,
        name: l.nickname,
        group: l.stage === 'intent' ? 'high_intent' : l.stage === 'showing' ? 'showing' : 'silent',
        tags: tags.length ? tags : ['风险客户'],
        summary: (l.risk_reasons || []).join('；') || '需关注',
        time: l.silence_days > 0 ? `${l.silence_days}天前` : '近期',
      };
    });
  } catch { return []; }
}

async function fetchActions() {
  try {
    const resp = await fetch('/api/leads/actions');
    if (!resp.ok) return [];
    const data = await resp.json();
    const actions = data.actions || [];
    return actions.map(a => ({
      id: a.id,
      name: a.nickname || a.wxid,
      group: 'high_intent',
      type: a.type,
      priority: a.priority || 'medium',
      desc: a.description || '',
      done: a.status !== 'pending',
      wxid: a.wxid,
    }));
  } catch { return []; }
}

async function fetchSources() {
  try {
    const resp = await fetch('/api/leads/risk');
    if (!resp.ok) return [];
    const data = await resp.json();
    const leads = data.leads || [];
    const sorted = [...leads].sort((a, b) => (b.message_count || 0) - (a.message_count || 0)).slice(0, 8);
    return sorted.map(l => {
      const profile = l.key_profile || {};
      const tags = [];
      if (l.stage === 'intent') tags.push('高意向');
      if (l.stage === 'showing') tags.push('带看中');
      if (profile.budget) tags.push(`预算 ${profile.budget}万`);
      if (profile.area) tags.push(profile.area);
      if (l.silence_days > 7) tags.push('沉默');
      return {
        name: l.nickname,
        group: l.stage === 'intent' ? 'high_intent' : l.stage === 'showing' ? 'showing' : 'silent',
        messages: l.message_count || 0,
        lastActive: l.silence_days > 0 ? `${l.silence_days}天前` : '近期',
        tags: tags.length ? tags : ['未分组'],
      };
    });
  } catch { return []; }
}

// ── Renderers ──

function renderKPI(k) {
  if (!k) {
    document.getElementById('kpiActive').textContent = '--';
    document.getElementById('kpiNewMsg').textContent = '--';
    document.getElementById('kpiPending').textContent = '--';
    document.getElementById('kpiSilent').textContent = '--';
    return;
  }
  document.getElementById('kpiActive').textContent = k.active || k.active_customers || 0;
  document.getElementById('kpiNewMsg').textContent = k.new_messages || k.new_messages_today || 0;
  document.getElementById('kpiPending').textContent = k.pending_reply || 0;
  document.getElementById('kpiSilent').textContent = k.silent || k.silent_customers || 0;
}

function renderBriefing(b) {
  if (!b) {
    document.getElementById('briefingContent').innerHTML = '<span style="color:var(--text-muted)">暂无简报数据，请先同步微信消息</span>';
    document.getElementById('briefingDate').textContent = '';
    return;
  }
  document.getElementById('briefingContent').innerHTML = b.text;
  document.getElementById('briefingDate').textContent = b.date;
}

function renderNotable() {
  const items = filterByGroup(state.notable || []);
  const list = document.getElementById('notableList');
  const count = document.getElementById('notableCount');
  count.textContent = items.length + ' 条';
  if (!items.length) { list.innerHTML = '<div class="empty-state">暂无</div>'; return; }
  list.innerHTML = items.map(n => `
    <div class="notable-card">
      <div class="notable-top">
        <span class="notable-name">${esc(n.name)}</span>
        <span class="notable-time">${esc(n.time)}</span>
      </div>
      <div class="notable-summary">${esc(n.summary)}</div>
      <div class="notable-tags">${n.tags.map(t => `<span class="tag ${tagClass(t)}">${esc(t)}</span>`).join('')}</div>
    </div>`).join('');
}

function renderActions() {
  const pending = filterByGroup(state.actions).filter(a => !a.done);
  const list = document.getElementById('actionList');
  const count = document.getElementById('actionCount');
  count.textContent = pending.length + ' 项';
  if (!pending.length) { list.innerHTML = '<div class="empty-state">✓ 全部完成</div>'; return; }
  list.innerHTML = pending.map(a => `
    <div class="action-card ${a.priority}" data-id="${a.id}" onclick="if(!event.target.closest('.action-checkbox'))window._openActionModal(${a.id})">
      <div class="action-checkbox" onclick="event.stopPropagation();window._completeAction(${a.id}, this)">✓</div>
      <div class="action-body">
        <div class="action-name">${esc(a.name)}</div>
        <div class="action-desc">${esc(a.desc)} <span style="color:var(--gold);font-size:10px">→ 生成话术</span></div>
      </div>
    </div>`).join('');
}

function renderSources() {
  const items = filterByGroup(state.sources || []);
  const list = document.getElementById('sourceList');
  const count = document.getElementById('sourceCount');
  count.textContent = items.length + ' 人';
  if (!items.length) { list.innerHTML = '<div class="empty-state">暂无</div>'; return; }
  list.innerHTML = items.map(s => `
    <div class="source-card">
      <div class="source-avatar">${esc(s.name[0])}</div>
      <div class="source-info">
        <div class="source-name">${esc(s.name)}</div>
        <div class="source-detail">${s.messages} 条 · ${esc(s.lastActive)}</div>
        <div class="source-tags">${s.tags.map(t => `<span class="tag ${tagClass(t)}">${esc(t)}</span>`).join('')}</div>
      </div>
    </div>`).join('');
}

function toggleBriefing() {
  document.getElementById('briefingCard').classList.toggle('open');
}

function showToast(message, type = 'success') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function copyBriefing() {
  const text = document.getElementById('briefingContent').innerText;
  navigator.clipboard.writeText(text).then(() => showToast('摘要已复制'));
}

// ── Group change callback ──

function onGroupChange(groupId) {
  state.activeGroup = groupId;
  renderNotable();
  renderActions();
  renderSources();
}

// Expose for inline handlers
window._completeAction = (id, el) => {
  // 乐观更新 UI
  const action = state.actions.find(a => a.id === id);
  if (action) action.done = true;
  const card = el.closest('.action-card');
  card.classList.add('done');
  // 调用后端标记完成
  fetch(`/api/leads/actions/${id}/done`, { method: 'POST' }).catch(() => {});
  setTimeout(() => renderActions(), 600);
};

window._toggleBriefing = toggleBriefing;
window._copyBriefing = copyBriefing;

// ── Init ──

export async function initDashboard() {
  document.getElementById('lastSync').textContent = '加载中...';

  // Init group manager
  const { renderGroups, setGroupChangeCallback } = await import('./group-manager.js');
  setGroupChangeCallback(onGroupChange);
  renderGroups();

  // Init sync modal
  await import('./sync-modal.js');

  // Init action modal
  await import('./action-modal.js');

  // Fetch real data in parallel
  const [kpi, briefing, notable, actions, sources, health] = await Promise.all([
    fetchKPI(),
    fetchBriefing(),
    fetchNotable(),
    fetchActions(),
    fetchSources(),
    fetchHealth(),
  ]);

  // Store real data
  state.kpi = kpi;
  state.briefing = briefing;
  state.notable = notable;
  state.actions = actions.map(a => ({ ...a }));
  state.sources = sources;

  // Render with real data
  renderEnvBar(health);
  renderKPI(kpi);
  renderBriefing(briefing);
  renderNotable();
  renderActions();
  renderSources();

  // Update last sync time
  const now = new Date();
  document.getElementById('lastSync').textContent =
    `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

  // Auto-open briefing on desktop
  if (window.innerWidth >= 768) {
    document.getElementById('briefingCard').classList.add('open');
  }
}

export function refreshDashboard() {
  // Re-fetch all data
  initDashboard();
}
