// Sidebar group management — backend-driven with local cache
// Groups are persisted in DB, loaded via /api/leads/groups

const PALETTE = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

let groups = []; // loaded from backend
let activeGroup = 'all';
let onGroupChange = null; // callback

export function getGroups() { return groups; }
export function getActiveGroup() { return activeGroup; }

export function setGroupChangeCallback(fn) {
  onGroupChange = fn;
}

// ── Data loading ──

async function fetchGroups() {
  try {
    const resp = await fetch('/api/leads/groups');
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.groups || [];
  } catch { return null; }
}

export async function renderGroups() {
  const backendGroups = await fetchGroups();
  if (backendGroups) {
    groups = backendGroups;
  }
  _renderGroupsHTML();
}

// ── Rendering ──

function _renderGroupsHTML() {
  const list = document.getElementById('groupList');
  if (!list) return;

  let html = '';
  groups.forEach(g => {
    const isActive = activeGroup === g.id;
    const isSystem = g.is_system || g.id === 'all';
    html += `
      <div class="sidebar-group ${isActive ? 'active' : ''}" data-group="${g.id}">
        <span class="sidebar-group-dot" style="background:${g.color}"></span>
        <span class="sidebar-group-name">${esc(g.name)}</span>
        <span class="sidebar-group-count">${g.count || 0}</span>
        ${!isSystem ? `
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

// ── CRUD via API ──

async function deleteGroup(id) {
  const g = groups.find(g => g.id === id);
  if (!g || g.is_system) return;
  if (!confirm(`删除分组「${g.name}」？`)) return;

  try {
    const resp = await fetch(`/api/leads/groups/${id}`, { method: 'DELETE' });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      alert(data.error || '删除失败');
      return;
    }
  } catch { return; }

  if (activeGroup === id) activeGroup = 'all';
  await renderGroups();
  if (onGroupChange) onGroupChange(activeGroup);
}

function openGroupModal() {
  const overlay = document.getElementById('groupModal');
  overlay.style.display = 'flex';
  document.getElementById('groupNameInput').value = '';
  const usedColors = groups.map(g => g.color);
  const nextColor = PALETTE.find(c => !usedColors.includes(c)) || PALETTE[0];
  document.getElementById('groupColorPreview').style.background = nextColor;
  document.getElementById('groupColorInput').value = nextColor;
  document.getElementById('groupNameInput').focus();
}

export function closeGroupModal() {
  document.getElementById('groupModal').style.display = 'none';
}

export async function submitNewGroup() {
  const name = document.getElementById('groupNameInput').value.trim();
  const color = document.getElementById('groupColorInput').value;
  if (!name) return;

  try {
    const resp = await fetch('/api/leads/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      alert(data.error || '创建失败');
      return;
    }
  } catch { return; }

  closeGroupModal();
  await renderGroups();
}

// ── Customer group assignment (used by dashboard cards) ──

export async function assignCustomerGroup(wxid, groupId) {
  try {
    const resp = await fetch(`/api/leads/customers/${encodeURIComponent(wxid)}/group`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      alert(data.error || '分组设置失败');
      return false;
    }
    // Refresh group counts
    await renderGroups();
    return true;
  } catch { return false; }
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Expose for inline onclick handlers
window._closeGroupModal = closeGroupModal;
window._submitNewGroup = submitNewGroup;
