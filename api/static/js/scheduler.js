// Scheduler — task CRUD and modal
import { state, getContactName, getDisplayName, getSecondaryName, describeCron, describeScanMode } from './state.js';
import { fetchSchedulerTasks, createSchedulerTask, deleteSchedulerTask, toggleSchedulerTask } from './api.js';

export function openTaskModal() {
  document.getElementById('taskModal').style.display = 'flex';
  populateModalContacts();
  document.getElementById('mTaskName').value = '';
  document.getElementById('mTime').value = '22:30';
  document.getElementById('mFreq').value = 'daily';
  document.getElementById('mCronGroup').style.display = 'none';
  document.getElementById('mCron').value = '';
  document.getElementById('mDateFields').classList.remove('visible');
  selectScanMode('today', document.querySelector('#scanModeGroup .radio-label'));
  document.getElementById('mEnabled').classList.add('on');
  document.getElementById('mTaskName').focus();
}

export function closeTaskModal() {
  document.getElementById('taskModal').style.display = 'none';
}

export function selectScanMode(mode, el) {
  document.querySelectorAll('#scanModeGroup .radio-label').forEach(l => l.classList.remove('checked'));
  el.classList.add('checked');
  el.querySelector('input').checked = true;
  document.getElementById('mDateFields').classList.toggle('visible', mode === 'range');
}

function populateModalContacts() {
  const sel = document.getElementById('mContact');
  sel.innerHTML = '';
  if (state.contactsList.length === 0) { sel.innerHTML = '<option value="">请先解密并加载联系人</option>'; return; }
  sel.innerHTML = '<option value="__all__">所有人</option>';
  state.contactsList.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.wxid;
    opt.textContent = getDisplayName(c) + (getSecondaryName(c) ? ' (' + getSecondaryName(c) + ')' : '');
    sel.appendChild(opt);
  });
}

function buildCronFromInputs() {
  const freq = document.getElementById('mFreq').value;
  const time = document.getElementById('mTime').value || '22:30';
  const [h, m] = time.split(':');
  if (freq === 'custom') return document.getElementById('mCron').value.trim() || (m + ' ' + h + ' * * *');
  if (freq === 'weekday') return m + ' ' + h + ' * * 1-5';
  return m + ' ' + h + ' * * *';
}

export async function submitTask() {
  const name = document.getElementById('mTaskName').value.trim() || ('task_' + Date.now());
  const contactId = document.getElementById('mContact').value;
  if (!contactId) { alert('请选择联系人'); return; }
  const enabled = document.getElementById('mEnabled').classList.contains('on');
  const scanMode = document.querySelector('#scanModeGroup input:checked').value;
  let dateStart = '', dateEnd = '';
  if (scanMode === 'range') {
    dateStart = document.getElementById('mDateStart').value || '';
    dateEnd = document.getElementById('mDateEnd').value || '';
    if (!dateStart || !dateEnd) { alert('请选择日期范围'); return; }
  }
  try {
    await createSchedulerTask({ task_id: name, cron: buildCronFromInputs(), contact_id: contactId, date_start: dateStart, date_end: dateEnd, scan_mode: scanMode, enabled: enabled });
    closeTaskModal();
    loadTasks();
  } catch (e) { alert(e.message); }
}

export async function loadTasks() {
  try {
    const data = await fetchSchedulerTasks();
    const list = document.getElementById('schedList');
    list.innerHTML = '';
    const tasks = data.tasks || {};
    if (Object.keys(tasks).length === 0) { list.innerHTML = '<div class="sched-empty">暂无定时任务，点击「新建任务」创建</div>'; return; }
    Object.entries(tasks).forEach(([id, task]) => {
      const contactName = task.contact_id === '__all__' ? '所有人' : getContactName(task.contact_id);
      const item = document.createElement('div');
      item.className = 'sched-item';
      item.innerHTML = '<div class="sched-info"><div class="sched-name">' + id + (contactName !== task.contact_id ? ' — ' + contactName : '') + '</div><div class="sched-desc">' + describeCron(task.cron) + ' · ' + describeScanMode(task.scan_mode, task.date_start, task.date_end) + '</div></div><div class="sched-actions"><div class="toggle ' + (task.enabled ? 'on' : '') + '" onclick="_toggleTask(\'' + id + '\',this)"></div><button class="btn btn-sm btn-danger" onclick="_deleteTask(\'' + id + '\')">删除</button></div>';
      list.appendChild(item);
    });
  } catch (e) { console.warn('加载任务失败', e); }
}

// Wrappers for inline onclick handlers
window._toggleTask = async (id, el) => {
  await toggleSchedulerTask(id, !el.classList.contains('on'));
  el.classList.toggle('on');
};
window._deleteTask = async (id) => {
  await deleteSchedulerTask(id);
  loadTasks();
};
