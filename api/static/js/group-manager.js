// Sidebar group CRUD — create and delete customer groups
// Fetches real group stats from backend, merges with user custom groups

const DEFAULT_GROUPS = [
  { id: 'all', name: '全部客户', color: '#9ca3af', count: 0, system: true },
  { id: 'high_intent', name: '高意向客户', color: '#10b981', count: 0 },
  { id: 'showing', name: '带看谈判中', color: '#3b82f6', count: 0 },
  { id: 'silent', name: '沉默预警', color: '#f59e0b', count: 0 },
  { id: 'closed', name: '已成交', color: '#c9a24d', count: 0 },
  { id: 'ungrouped', name: '未分组', color: '#6b7280', count: 0, system: true },
];

const PALETTE = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

let groups = loadGroups();
let activeGroup = 'all';
let onGroupChange = null; // callback

// Map backend group id → our group structure
const GROUP_ID_MAP = {
  'high_intent': { name: '高意向客户', color: '#10b981' },
  'showing': { name: '带看谈判中', color: '#3b82f6' },
  'silent': { name: '沉默预警', color: '#f59e0b' },
  'closed': { name: '已成交', color: '#c9a24d' },
  'ungrouped': { name: '未分组', color: '#6b7280' },
};

function loadGroups() {
  try {
    const saved = localStorage.getItem('realty_groups');
    if (saved) return JSON.parse(saved);
  } catch {}
  return DEFAULT_GROUPS.map(g => ({ ...g }));
}

function saveGroups() {
  localStorage.setItem('realty_groups', JSON.stringify(groups));
}

export function getGroups() { return groups; }
export function getActiveGroup() { return activeGroup; }

export function setGroupChangeCallback(fn) {
  onGroupChange = fn;
}

async function fetchGroupStats() {
  try {
    const resp = await fetch('/api/leads/groups');
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.groups || [];
  } catch { return null; }
}

function mergeBackendStats(backendGroups) {
  if (!backendGroups || !backendGroups.length) return;

  // Build a lookup from backend data
  const backendMap = {};
  let totalCount = 0;
  for (const g of backendGroups) {
    backendMap[g.id] = g.count || 0;
    totalCount += g.count || 0;
  }

  // Update existing groups with real counts
  for (const g of groups) {
    if (g.id === 'all') {
      g.count = totalCount;
    } else if (backendMap[g.id] !== undefined) {
      g.count = backendMap[g.id];
    }
  }
  saveGroups();
}

export function renderGroups() {
  // First render, then fetch real stats in background
  _renderGroupsHTML();

  // Fetch real stats and re-render
  fetchGroupStats().then(backendGroups => {
    if (backendGroups) {
      mergeBackendStats(backendGroups);
      _renderGroupsHTML();
    }
  });
}

function _renderGroupsHTML() {
  const list = document.getElementById('groupList');
  if (!list) return;

  let html = '';
  groups.forEach(g => {
    const isActive = activeGroup === g.id;
    html += `
      <div class="sidebar-group ${isActive ? 'active' : ''}" data-group="${g.id}">
        <span class="sidebar-group-dot" style="background:${g.color}"></span>
        <span class="sidebar-group-name">${esc(g.name)}</span>
        <span class="sidebar-group-count">${g.count}</span>
        ${!g.system ? `
          <div class="sidebar-group-actions">
            <button class="sidebar-group-btn delete" data-delete="${g.id}" title="删除分组">✕</button>
          </div>` : ''}
      </div>`;
  });
  html += `<div class="sidebar-add-group" id="addGroupBtn">＋ 新建分组</div>`;
  list.innerHTML = html;

  // Bind click
  list.querySelectorAll('.sidebar-group').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.closest('.sidebar-group-btn')) return;
      selectGroup(el.dataset.group);
    });
  });
  list.querySelectorAll('[data-delete]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteGroup(btn.dataset.delete);
    });
  });
  document.getElementById('addGroupBtn')?.addEventListener('click', openGroupModal);
}

function selectGroup(id) {
  activeGroup = id;
  _renderGroupsHTML();
  if (onGroupChange) onGroupChange(id);
}

function deleteGroup(id) {
  const g = groups.find(g => g.id === id);
  if (!g || g.system) return;
  if (!confirm(`删除分组「${g.name}」？`)) return;
  groups = groups.filter(g => g.id !== id);
  saveGroups();
  if (activeGroup === id) activeGroup = 'all';
  _renderGroupsHTML();
  if (onGroupChange) onGroupChange(activeGroup);
}

function openGroupModal() {
  const overlay = document.getElementById('groupModal');
  overlay.style.display = 'flex';
  document.getElementById('groupNameInput').value = '';
  // Pick next color from palette
  const usedColors = groups.map(g => g.color);
  const nextColor = PALETTE.find(c => !usedColors.includes(c)) || PALETTE[Math.floor(Math.random() * PALETTE.length)];
  document.getElementById('groupColorPreview').style.background = nextColor;
  document.getElementById('groupColorInput').value = nextColor;
  document.getElementById('groupNameInput').focus();
}

export function closeGroupModal() {
  document.getElementById('groupModal').style.display = 'none';
}

export function submitNewGroup() {
  const name = document.getElementById('groupNameInput').value.trim();
  const color = document.getElementById('groupColorInput').value;
  if (!name) return;
  const id = 'custom_' + Date.now();
  groups.push({ id, name, color, count: 0 });
  saveGroups();
  closeGroupModal();
  _renderGroupsHTML();
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Expose
window._closeGroupModal = closeGroupModal;
window._submitNewGroup = submitNewGroup;
