// Sync modal — date range picker + scheduled sync option
// Shows real-time pipeline progress via SSE
import { createSchedulerTask } from './api.js';

let _esc = null;
async function getEsc() {
  if (!_esc) { const m = await import('./state.js'); _esc = m.escHtml; }
  return _esc;
}

export function openSyncModal() {
  const overlay = document.getElementById('syncModal');
  overlay.style.display = 'flex';
  // Reset form
  document.getElementById('syncDateStart').value = defaultDate(-7);
  document.getElementById('syncDateEnd').value = defaultDate(0);
  document.getElementById('syncModeNow').checked = true;
  document.getElementById('syncDateFields').style.display = '';
  document.getElementById('syncScheduleFields').style.display = 'none';
  // Reset progress area
  const progressArea = document.getElementById('syncProgress');
  if (progressArea) progressArea.style.display = 'none';
  updateSyncRadioUI();
}

export function closeSyncModal() {
  document.getElementById('syncModal').style.display = 'none';
}

function defaultDate(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function updateSyncRadioUI() {
  const mode = document.querySelector('input[name="syncMode"]:checked').value;
  document.getElementById('syncDateFields').style.display = mode === 'now' ? '' : 'none';
  document.getElementById('syncScheduleFields').style.display = mode === 'schedule' ? '' : 'none';
  document.querySelectorAll('#syncModal .radio-label').forEach(el => {
    el.classList.toggle('checked', el.querySelector('input').checked);
  });
}

async function submitSync() {
  const mode = document.querySelector('input[name="syncMode"]:checked').value;
  if (mode === 'now') {
    await submitImmediateSync();
  } else {
    await submitScheduledSync();
  }
}

function ensureProgressArea() {
  let area = document.getElementById('syncProgress');
  if (!area) {
    area = document.createElement('div');
    area.id = 'syncProgress';
    area.style.cssText = 'margin-top:16px;padding:12px;background:var(--surface);border-radius:8px;font-size:13px;';
    const footer = document.querySelector('#syncModal .modal-footer');
    footer.parentNode.insertBefore(area, footer);
  }
  area.style.display = '';
  return area;
}

function updateProgress(text, type = 'info') {
  const area = ensureProgressArea();
  const colors = { info: 'var(--gold)', success: 'var(--green)', error: 'var(--red)', step: 'var(--text-muted)' };
  const icons = { info: '⏳', success: '✅', error: '❌', step: '→' };
  const line = document.createElement('div');
  line.style.cssText = `color:${colors[type] || colors.info};margin:4px 0;`;
  line.textContent = `${icons[type] || '⏳'} ${text}`;
  area.appendChild(line);
  area.scrollTop = area.scrollHeight;
}

function listenPipelineProgress(runId) {
  const evtSource = new EventSource('/api/logs/stream');
  let lastStepCount = 0;

  const onMessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }

    // Only care about events for our run
    if (data.run_id && data.run_id !== runId) return;

    if (data.type === 'pipeline_start') {
      updateProgress('管道已启动，开始解密数据库...', 'info');
    }
    if (data.type === 'tool_start') {
      const stepLabels = {
        decrypt_db: '解密数据库', extract_dm: '提取聊天记录',
        parse_profile: 'AI 画像解析', sync_feishu: '同步飞书',
      };
      updateProgress(`${stepLabels[data.tool] || data.tool} 开始...`, 'step');
    }
    if (data.type === 'tool_end') {
      const stepLabels = {
        decrypt_db: '解密数据库', extract_dm: '提取聊天记录',
        parse_profile: 'AI 画像解析', sync_feishu: '同步飞书',
      };
      updateProgress(`${stepLabels[data.tool] || data.tool} ✓ ${data.output || ''}`, 'success');
    }
    if (data.type === 'tool_error') {
      updateProgress(`错误: ${data.error || '未知'}`, 'error');
    }
    if (data.type === 'pipeline_progress') {
      updateProgress(data.message || '处理中...', 'step');
    }
    if (data.type === 'pipeline_end') {
      const status = data.status === 'failed' ? 'error' : 'success';
      const msg = data.message || data.error || (status === 'error' ? '失败' : '完成');
      updateProgress(`管道${status === 'error' ? '失败' : '完成'}: ${msg}`, status);
      evtSource.close();
      // Re-enable button
      const btn = document.getElementById('syncSubmitBtn');
      btn.classList.remove('btn-loading');
      btn.disabled = false;
      btn.textContent = '开始同步';
      // Refresh dashboard data after success
      if (status === 'success') {
        setTimeout(() => {
          import('./dashboard.js').then(m => m.refreshDashboard());
          updateProgress('看板数据已刷新', 'success');
        }, 500);
      }
    }
  };

  evtSource.onmessage = onMessage;
  evtSource.onerror = () => {
    // SSE connection lost, try to check status via polling
    evtSource.close();
    // Fallback: poll status 3 times
    let polls = 0;
    const poll = setInterval(async () => {
      polls++;
      try {
        const resp = await fetch('/api/workflow/status');
        const data = await resp.json();
        if (!data.current_run) {
          clearInterval(poll);
          updateProgress('同步完成', 'success');
          const btn = document.getElementById('syncSubmitBtn');
          btn.classList.remove('btn-loading');
          btn.disabled = false;
          btn.textContent = '开始同步';
          import('./dashboard.js').then(m => m.refreshDashboard());
        }
      } catch {}
      if (polls >= 30) clearInterval(poll);
    }, 2000);
  };

  // Safety timeout — close SSE after 5 min
  setTimeout(() => { evtSource.close(); }, 300000);
}

async function submitImmediateSync() {
  const dateStart = document.getElementById('syncDateStart').value;
  const dateEnd = document.getElementById('syncDateEnd').value;
  const btn = document.getElementById('syncSubmitBtn');
  btn.classList.add('btn-loading');
  btn.disabled = true;
  btn.textContent = '同步中...';

  // Clear previous progress
  ensureProgressArea().innerHTML = '';
  updateProgress('正在启动同步管道...', 'info');

  try {
    const resp = await fetch('/api/workflow/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contact_id: '__all__',
        date_start: dateStart || null,
        date_end: dateEnd || null,
        parse_only: false,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      updateProgress(`管道已创建 (run: ${data.run_id})`, 'info');
      // Listen to SSE for progress
      listenPipelineProgress(data.run_id);
    } else {
      const err = await resp.json().catch(() => ({}));
      updateProgress(`启动失败: ${err.detail || resp.status}`, 'error');
      btn.classList.remove('btn-loading');
      btn.disabled = false;
      btn.textContent = '开始同步';
    }
  } catch (e) {
    updateProgress('后端未连接，请检查服务器是否启动', 'error');
    btn.classList.remove('btn-loading');
    btn.disabled = false;
    btn.textContent = '开始同步';
  }
}

async function submitScheduledSync() {
  const time = document.getElementById('syncScheduleTime').value || '22:30';
  const freq = document.getElementById('syncScheduleFreq').value || 'daily';
  const dateStart = document.getElementById('syncScheduleDateStart').value || '';
  const dateEnd = document.getElementById('syncScheduleDateEnd').value || '';
  const [h, m] = time.split(':');
  let cron;
  if (freq === 'weekday') cron = `${m} ${h} * * 1-5`;
  else if (freq === 'weekly') cron = `${m} ${h} * * 1`;
  else cron = `${m} ${h} * * *`;

  const taskId = 'sync_' + Date.now();
  try {
    await createSchedulerTask({
      task_id: taskId,
      cron,
      contact_id: '__all__',
      date_start: dateStart,
      date_end: dateEnd,
      scan_mode: 'range',
      enabled: true,
    });
    showToast(`定时同步已创建 (${freq === 'weekday' ? '工作日' : freq === 'weekly' ? '每周' : '每天'} ${time})`);
    closeSyncModal();
  } catch (e) {
    showToast('创建定时任务失败: ' + e.message, 'error');
  }
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

// Expose for inline handlers
window._openSyncModal = openSyncModal;
window._closeSyncModal = closeSyncModal;
window._updateSyncRadioUI = updateSyncRadioUI;
window._submitSync = submitSync;
