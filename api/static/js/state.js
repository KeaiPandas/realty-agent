// Shared state, constants, and utility functions

export const API = '';

export const STEPS = ['decrypt_db', 'extract_dm', 'parse_profile', 'sync_feishu'];
export const STEP_LABELS = { decrypt_db: '解密', extract_dm: '提取', parse_profile: '解析', sync_feishu: '同步' };
export const STEP_NAMES = {
  decrypt_db: '解密数据库',
  extract_dm: '提取聊天记录',
  parse_profile: 'AI 画像解析',
  sync_feishu: '同步飞书',
  pipeline_start: '管道启动',
  pipeline_end: '管道结束',
  pipeline_progress: '处理进度',
};

export const state = {
  currentRunId: null,
  selectedRunId: null,
  currentTaskTab: 'running',
  contactsList: [],
  selectedContactId: '',
  selectedContactName: '',
  cpOpen: false,
};

export const pipelineRuns = {};
export const logEntries = [];
export const renderedLogIds = new Set();

// ── Callback registry (breaks circular deps) ──
let _stopRunFn = null;
let _setPipelineRunningFn = null;
let _renderTaskListFn = null;

export function onStopRun(fn) { _stopRunFn = fn; }
export function onSetPipelineRunning(fn) { _setPipelineRunningFn = fn; }
export function onRenderTaskList(fn) { _renderTaskListFn = fn; }

export function stopRun(runId) { return _stopRunFn?.(runId); }
export function setPipelineRunning(running, contactId) { return _setPipelineRunningFn?.(running, contactId); }
export function renderTaskList() { return _renderTaskListFn?.(); }

// ── Utility functions ──
export function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

export function getDisplayName(c) {
  if (c.alias && c.alias.trim()) return c.alias;
  if (c.nickname && c.nickname.trim()) return c.nickname;
  return c.wxid;
}

export function getSecondaryName(c) {
  const parts = [];
  if (c.alias && c.alias.trim() && c.nickname && c.nickname.trim()) parts.push(c.nickname);
  return parts.join(' · ');
}

export function getContactName(wxid) {
  if (wxid === '__all__') return '所有人';
  const c = state.contactsList.find(c => c.wxid === wxid);
  return c ? getDisplayName(c) : wxid;
}

export function describeCron(cron) {
  if (!cron) return '未知时间';
  const p = cron.split(/\s+/);
  if (p.length !== 5) return cron;
  if (p[4] === '1-5') return p[1] + ':' + p[0] + ' 工作日';
  if (p[2] === '*' && p[4] === '*') return p[1] + ':' + p[0] + ' 每天';
  return cron;
}

export function describeScanMode(mode, ds, de) {
  if (mode === 'today') return '扫描今日消息';
  if (mode === 'all') return '扫描全部消息';
  if (mode === 'range' && ds && de) return ds + ' ~ ' + de;
  return mode || '未知';
}
