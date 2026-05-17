// Pipeline control — start, stop, decrypt, polling
import { state, pipelineRuns, onStopRun, onSetPipelineRunning, onRenderTaskList, getContactName } from './state.js';
import { fetchRuns, fetchContacts, fetchDecrypt, startPipelineAPI, stopPipelineAPI } from './api.js';
import { filterLogs, loadHistoricalLogs } from './logs.js';

// Register implementations for circular-dep callbacks
onStopRun(stopRunImpl);
onSetPipelineRunning(setPipelineRunningImpl);
onRenderTaskList(renderTaskListImpl);

function setPipelineRunningImpl(running, contactId) {
  document.getElementById('btnStart').disabled = running;
  const statusEl = document.getElementById('pipelineStatus');
  if (running) {
    statusEl.textContent = '运行中: ' + (contactId === '__all__' ? '所有人' : (contactId || ''));
    statusEl.style.color = 'var(--amber)';
  } else {
    statusEl.textContent = '';
  }
}

function renderTaskListImpl() {
  // Delegate to tasks module — will be overridden after import
  // This is a placeholder; the real render is imported directly by callers
}

export function setPipelineRunning(running, contactId) { setPipelineRunningImpl(running, contactId); }

export async function startPipeline() {
  if (!state.selectedContactId) { alert('请先选择联系人'); return; }
  const dateStart = document.getElementById('dateStart').value || null;
  const dateEnd = document.getElementById('dateEnd').value || null;
  const parseOnly = document.getElementById('chkParseOnly').checked;
  try {
    const { ok, data } = await startPipelineAPI({
      contact_id: state.selectedContactId,
      date_start: dateStart,
      date_end: dateEnd,
      parse_only: parseOnly,
    });
    if (!ok) { alert(data.detail || '启动失败'); return; }
    const rid = data.run_id;
    state.currentRunId = rid;
    state.selectedRunId = rid;
    const contactName = state.selectedContactId === '__all__' ? '所有人' : state.selectedContactName;
    pipelineRuns[rid] = {
      id: rid, contact: state.selectedContactId, contact_name: contactName,
      status: 'running', steps: {},
      startTime: new Date().toLocaleString('zh-CN'),
      endTime: '', error: '', message: '启动中...', stepOutputs: {},
    };
    setPipelineRunning(true, state.selectedContactId);
    // renderTaskList is imported from tasks.js — use callback to avoid circular dep
    const { renderTaskList } = await import('./tasks.js');
    renderTaskList();
    filterLogs();
  } catch (e) {
    alert('请求失败: ' + e.message);
  }
}

async function stopRunImpl(runId) {
  await stopPipelineAPI(runId);
  if (pipelineRuns[runId]) {
    pipelineRuns[runId].status = 'completed';
    pipelineRuns[runId].message = '已停止';
    pipelineRuns[runId].endTime = new Date().toLocaleString('zh-CN');
  }
  if (runId === state.currentRunId) {
    state.currentRunId = null;
    setPipelineRunning(false);
  }
  const { renderTaskList } = await import('./tasks.js');
  renderTaskList();
}

export async function stopRun(runId) { return stopRunImpl(runId); }

export async function loadRuns() {
  try {
    const data = await fetchRuns();
    if (!data || !data.runs || data.runs.length === 0) return;
    data.runs.forEach(run => {
      if (!pipelineRuns[run.id] || pipelineRuns[run.id].status !== 'running') {
        pipelineRuns[run.id] = run;
      }
    });
    const active = data.runs.find(r => r.status === 'running');
    if (active) {
      state.currentRunId = active.id;
      state.selectedRunId = active.id;
      setPipelineRunning(true, active.contact);
    } else {
      state.selectedRunId = data.runs[0].id;
    }
    const { renderTaskList } = await import('./tasks.js');
    renderTaskList();
  } catch (e) {
    console.warn('加载运行记录失败', e);
  }
}

export async function decryptDB() {
  const btn = document.getElementById('btnDecrypt');
  const status = document.getElementById('decryptStatus');
  btn.disabled = true;
  status.className = 'decrypt-status loading';
  status.textContent = '解密中...';
  try {
    const data = await fetchDecrypt();
    if (data.status === 'ok') {
      status.className = 'decrypt-status done';
      status.textContent = '已解密 ' + data.databases.length + ' 个库';
      const { loadContacts } = await import('./contacts.js');
      await loadContacts();
    } else {
      status.className = 'decrypt-status error';
      status.textContent = '解密失败: ' + (data.message || '');
    }
  } catch (e) {
    status.className = 'decrypt-status error';
    status.textContent = '请求失败';
  }
  btn.disabled = false;
}

export function pollUpdates() {
  fetchRuns().then(data => {
    if (!data || !data.runs) return;
    let changed = false;
    data.runs.forEach(run => {
      const existing = pipelineRuns[run.id];
      if (!existing || existing.status === 'running' || run.status !== existing.status) {
        pipelineRuns[run.id] = run;
        changed = true;
      }
    });
    const hasRunning = data.runs.some(r => r.status === 'running');
    if (hasRunning) {
      setPipelineRunning(true, '');
      state.currentRunId = data.runs.find(r => r.status === 'running').id;
    }
    if (changed) {
      import('./tasks.js').then(m => m.renderTaskList());
    }
    if (hasRunning) loadHistoricalLogs();
  }).catch(() => {});
}
