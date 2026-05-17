// Log cards — CRUD and historical loading
import { state, logEntries, renderedLogIds, STEP_NAMES, escHtml } from './state.js';
import { fetchLogs } from './api.js';

export function addLogCard(data) {
  const list = document.getElementById('logList');
  const id = data.id || 'sys-' + Date.now();
  if (renderedLogIds.has(id)) return;
  renderedLogIds.add(id);
  if (list.querySelector('.empty')) list.innerHTML = '';
  const name = STEP_NAMES[data.tool] || data.tool || '系统';
  const runId = data.run_id || '';
  const statusCls = data.status === 'error' ? 'error' : data.status === 'success' ? 'success' : 'running';
  const statusLabel = data.status === 'error' ? '失败' : data.status === 'success' ? '成功' : '运行中';
  const card = document.createElement('div');
  card.className = 'log-card ' + statusCls;
  card.id = 'log-' + id;
  card.setAttribute('data-log-run', runId);
  card.style.display = (!state.selectedRunId || runId === state.selectedRunId) ? '' : 'none';
  let html =
    '<div class="log-top">' +
      '<span class="log-tool">' + name + '</span>' +
      '<span class="log-badge ' + statusCls + '">' + statusLabel + '</span>' +
    '</div>' +
    '<div class="log-detail">' + escHtml(data.output || data.error || data.input || data.contact_id || data.message || '') + '</div>' +
    '<div class="log-time">' + (data.timestamp || '') + '</div>';
  if (data.duration_ms) html += '<div class="log-duration">' + data.duration_ms + 'ms</div>';
  card.innerHTML = html;
  if (data.error) card.querySelector('.log-detail').style.color = 'var(--coral)';
  list.prepend(card);
  logEntries.push({ id, runId });
  _updateLogCount();
}

function _updateLogCount() {
  let visible = 0;
  document.querySelectorAll('#logList .log-card').forEach(c => { if (c.style.display !== 'none') visible++; });
  document.getElementById('logCount').textContent = visible;
}

export function updateLogCard(data) {
  const card = document.getElementById('log-' + data.id);
  if (!card) return;
  const status = data.status;
  const label = status === 'success' ? '成功' : '失败';
  card.className = 'log-card ' + status;
  card.querySelector('.log-badge').className = 'log-badge ' + status;
  card.querySelector('.log-badge').textContent = label;
  if (data.duration_ms) {
    const dur = document.createElement('div');
    dur.className = 'log-duration';
    dur.textContent = data.duration_ms + 'ms';
    card.appendChild(dur);
  }
  if (data.output) card.querySelector('.log-detail').textContent = data.output;
  if (data.error) {
    card.querySelector('.log-detail').textContent = data.error;
    card.querySelector('.log-detail').style.color = 'var(--coral)';
  }
}

export function addSystemLog(msg, status) {
  const list = document.getElementById('logList');
  const card = document.createElement('div');
  card.className = 'log-card ' + status;
  card.setAttribute('data-log-run', state.currentRunId || '');
  card.style.display = (!state.selectedRunId || (state.currentRunId || '') === state.selectedRunId) ? '' : 'none';
  card.innerHTML =
    '<div class="log-top">' +
      '<span class="log-tool" style="color:var(--text-dim)">系统</span>' +
      '<span class="log-badge ' + status + '">' + (status === 'error' ? '失败' : status === 'running' ? '进行中' : '完成') + '</span>' +
    '</div>' +
    '<div class="log-detail">' + msg + '</div>' +
    '<div class="log-time">' + new Date().toLocaleString('zh-CN') + '</div>';
  list.prepend(card);
}

export function filterLogs() {
  document.querySelectorAll('#logList .log-card').forEach(card => {
    const runId = card.getAttribute('data-log-run') || '';
    card.style.display = (!state.selectedRunId || runId === state.selectedRunId) ? '' : 'none';
  });
  _updateLogCount();
}

export async function loadHistoricalLogs() {
  try {
    const data = await fetchLogs(200);
    if (!data || !data.entries || data.entries.length === 0) return;
    const entries = data.entries;
    entries.forEach(entry => {
      if (entry.type === 'tool_start' || entry.type === 'tool_end' || entry.type === 'tool_error') {
        addLogCard(entry);
      }
      if (entry.type === 'pipeline_start') {
        addLogCard({
          id: 'pipe-' + entry.run_id,
          tool: 'pipeline_start',
          run_id: entry.run_id,
          status: 'success',
          input: '启动: ' + (entry.contact_id === '__all__' ? '所有人' : entry.contact_id),
          timestamp: entry.timestamp,
        });
      }
      if (entry.type === 'pipeline_end') {
        addLogCard({
          id: 'pipe-end-' + entry.run_id,
          tool: 'pipeline_end',
          run_id: entry.run_id,
          status: entry.status === 'failed' ? 'error' : 'success',
          output: entry.message || entry.error || (entry.status === 'failed' ? '失败' : '完成'),
          timestamp: entry.timestamp,
        });
      }
      if (entry.type === 'pipeline_progress') {
        addLogCard({
          id: 'prog-' + entry.timestamp + '-' + Math.random().toString(36).slice(2, 6),
          tool: 'pipeline_progress',
          run_id: entry.run_id || '',
          status: 'running',
          input: entry.message || '',
          timestamp: entry.timestamp,
        });
      }
    });
    filterLogs();
  } catch (e) {
    console.warn('加载历史日志失败', e);
  }
}
