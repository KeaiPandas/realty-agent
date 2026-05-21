// Bot Panel — state, rendering, SSE events
import { escHtml } from './state.js';
import {
  fetchBotStatus, startBot, stopBot,
  fetchBotConversations, fetchBotMessages,
  approveReply, rejectReply, sendManualMessage,
  fetchBotSettings, updateBotSettings,
} from './api.js';

// ── State ──

const botState = {
  status: { running: false, uptime: 0, active_conversations: 0, pending_replies: 0 },
  conversations: [],
  contactSettings: {},  // { wxid: { mode, enabled } }
  selectedWxid: '',
  messages: {},
  pollTimer: null,
  sseSource: null,
};

// ── Mode labels ──

const MODE_LABELS = {
  auto: '全自动',
  semi_auto: '半自动',
};
const MODE_DISABLED = 'disabled';

// ── Control ──

export async function toggleBot() {
  if (botState.status.running) {
    await stopBot();
  } else {
    await startBot();
  }
  await refreshBotStatus();
}

async function refreshBotStatus() {
  try {
    botState.status = await fetchBotStatus();
  } catch { /* ignore */ }
  renderBotControl();
}

function renderBotControl() {
  const s = botState.status;
  const btn = document.getElementById('botToggleBtn');
  const info = document.getElementById('botInfo');
  if (!btn || !info) return;

  btn.textContent = s.running ? 'STOP' : 'START';
  btn.className = s.running ? 'btn btn-danger' : 'btn btn-primary';
  btn.disabled = false;

  const uptime = s.running ? Math.floor(s.uptime) : 0;
  const uptimeStr = uptime > 60 ? `${Math.floor(uptime / 60)}m ${uptime % 60}s` : `${uptime}s`;
  const parts = [s.running ? `Running ${uptimeStr}` : 'Stopped'];
  parts.push(`Contacts: ${s.active_conversations} active`);
  if (s.pending_replies > 0) parts.push(`<span style="color:var(--amber)">${s.pending_replies} pending</span>`);
  info.innerHTML = parts.join(' · ');
}

// ── Settings ──

async function loadContactSettings() {
  try {
    const list = await fetchBotSettings();
    botState.contactSettings = {};
    for (const s of list) {
      botState.contactSettings[s.wxid] = s;
    }
  } catch { /* ignore */ }
}

async function setContactMode(wxid, mode) {
  const enabled = mode !== MODE_DISABLED;
  const actualMode = mode === MODE_DISABLED ? 'semi_auto' : mode;
  try {
    const result = await updateBotSettings(wxid, actualMode, enabled);
    botState.contactSettings[wxid] = result;
  } catch { /* ignore */ }
  renderConversations();
}

// ── Conversations ──

async function loadConversations() {
  try {
    botState.conversations = await fetchBotConversations();
  } catch { /* ignore */ }
  renderConversations();
}

function getContactMode(wxid) {
  const s = botState.contactSettings[wxid];
  if (!s || !s.enabled) return MODE_DISABLED;
  return s.mode || 'semi_auto';
}

function renderConversations() {
  const list = document.getElementById('convList');
  if (!list) return;

  if (botState.conversations.length === 0) {
    list.innerHTML = '<div class="conv-empty">暂无会话</div>';
    return;
  }

  list.innerHTML = botState.conversations.map(c => {
    const selected = c.wxid === botState.selectedWxid ? ' selected' : '';
    const pending = c.pending_reply ? ' has-pending' : '';
    const badge = c.pending_reply ? '<div class="conv-badge"></div>' : '';
    const mode = getContactMode(c.wxid);
    const modeLabel = mode === MODE_DISABLED ? '关闭' : (MODE_LABELS[mode] || mode);
    const modeClass = mode === MODE_DISABLED ? 'mode-off' : `mode-${mode}`;
    return `<div class="conv-item${selected}${pending}" data-wxid="${escHtml(c.wxid)}">
      <div class="conv-avatar">${(c.nickname || c.wxid)[0].toUpperCase()}</div>
      <div class="conv-info">
        <div class="conv-name">${escHtml(c.nickname || c.wxid)}</div>
        <div class="conv-preview">${c.last_message_time || ''} · ${c.message_count} 条</div>
      </div>
      <div class="conv-mode-wrap">
        <select class="conv-mode-select ${modeClass}" data-wxid="${escHtml(c.wxid)}">
          <option value="auto" ${mode === 'auto' ? 'selected' : ''}>全自动</option>
          <option value="semi_auto" ${mode === 'semi_auto' ? 'selected' : ''}>半自动</option>
          <option value="disabled" ${mode === MODE_DISABLED ? 'selected' : ''}>关闭</option>
        </select>
      </div>
      ${badge}
    </div>`;
  }).join('');

  // Click to select conversation (not on the select)
  list.querySelectorAll('.conv-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.tagName !== 'SELECT' && e.target.tagName !== 'OPTION') {
        selectConversation(el.dataset.wxid);
      }
    });
  });

  // Mode change handlers
  list.querySelectorAll('.conv-mode-select').forEach(sel => {
    sel.addEventListener('change', (e) => {
      e.stopPropagation();
      setContactMode(sel.dataset.wxid, sel.value);
    });
  });
}

async function selectConversation(wxid) {
  botState.selectedWxid = wxid;
  renderConversations();
  await loadMessages(wxid);
  renderReplyPanel();
}

// ── Messages ──

async function loadMessages(wxid) {
  try {
    botState.messages[wxid] = await fetchBotMessages(wxid);
  } catch { /* ignore */ }
  renderMessages();
}

function renderMessages() {
  const thread = document.getElementById('msgThread');
  if (!thread) return;

  const wxid = botState.selectedWxid;
  const msgs = botState.messages[wxid] || [];

  if (!wxid || msgs.length === 0) {
    thread.innerHTML = '<div class="msg-empty">' + (!wxid ? '选择一个会话开始查看消息' : '暂无消息记录') + '</div>';
    return;
  }

  thread.innerHTML = msgs.map(m => {
    const side = m.is_from_customer ? 'customer' : 'self';
    const sender = m.is_from_customer ? '客户' : '我方';
    return `<div class="msg-bubble ${side}">
      <div class="msg-meta"><span class="msg-sender">${sender}</span><span class="msg-time">${escHtml(m.timestamp)}</span></div>
      <div class="msg-content">${escHtml(m.content)}</div>
    </div>`;
  }).join('');

  thread.scrollTop = thread.scrollHeight;
}

// ── Reply Panel ──

function renderReplyPanel() {
  const panel = document.getElementById('replyPanel');
  if (!panel) return;

  const wxid = botState.selectedWxid;
  const conv = botState.conversations.find(c => c.wxid === wxid);
  const pending = conv?.pending_reply;

  if (!pending || pending.reply_status !== 'pending') {
    panel.innerHTML = '<div class="reply-empty">无待审批回复</div>';
    return;
  }

  panel.innerHTML = `
    <div class="reply-header">AI 建议回复</div>
    <div class="reply-original">
      <div class="reply-label">客户消息</div>
      <div class="reply-text">${escHtml(pending.content)}</div>
    </div>
    <div class="reply-suggestion">
      <div class="reply-label">AI 建议</div>
      <textarea class="reply-textarea" id="replyEdit" rows="4">${escHtml(pending.reply)}</textarea>
    </div>
    <div class="reply-actions">
      <button class="btn btn-primary" id="btnApprove">批准</button>
      <button class="btn btn-danger" id="btnReject">拒绝</button>
    </div>`;

  document.getElementById('btnApprove').addEventListener('click', async () => {
    const edited = document.getElementById('replyEdit').value;
    await approveReply(wxid, edited);
    await loadConversations();
    renderReplyPanel();
  });
  document.getElementById('btnReject').addEventListener('click', async () => {
    await rejectReply(wxid);
    await loadConversations();
    renderReplyPanel();
  });
}

// ── SSE Events ──

function connectBotSSE() {
  if (botState.sseSource) botState.sseSource.close();
  botState.sseSource = new EventSource('/api/bot/stream');

  botState.sseSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      handleBotEvent(data);
    } catch { /* ignore */ }
  };
}

function handleBotEvent(data) {
  if (data.type === 'bot.status_change') {
    refreshBotStatus();
  }
  if (data.type === 'bot.new_message' || data.type === 'bot.reply_generated'
      || data.type === 'bot.reply_sent' || data.type === 'bot.reply_rejected') {
    loadConversations();
    if (botState.selectedWxid === data.wxid) {
      loadMessages(botState.selectedWxid);
      renderReplyPanel();
    }
  }
}

// ── Init ──

export async function initBotPanel() {
  await refreshBotStatus();
  await loadContactSettings();
  await loadConversations();
  connectBotSSE();

  // Poll every 10s
  botState.pollTimer = setInterval(async () => {
    await refreshBotStatus();
    await loadContactSettings();
    await loadConversations();
    if (botState.selectedWxid) {
      await loadMessages(botState.selectedWxid);
      renderReplyPanel();
    }
  }, 10000);
}

export function destroyBotPanel() {
  if (botState.pollTimer) clearInterval(botState.pollTimer);
  if (botState.sseSource) botState.sseSource.close();
  botState.pollTimer = null;
  botState.sseSource = null;
}
