// Bot panel state, rendering, and SSE events.
import { escHtml } from './state.js';
import {
  approveReply,
  fetchBotConversations,
  fetchBotGlobalSettings,
  fetchBotMessages,
  fetchBotSettings,
  fetchBotStatus,
  rejectReply,
  startBot,
  stopBot,
  updateBotGlobalSettings,
  updateBotSettings,
} from './api.js';

const botState = {
  status: {
    running: false,
    uptime: 0,
    active_conversations: 0,
    pending_replies: 0,
    transport_mode: 'desktop_rpa',
  },
  globalSettings: { mode: 'semi_auto', enabled: false },
  conversations: [],
  contactSettings: {},
  selectedWxid: '',
  messages: {},
  pollTimer: null,
  sseSource: null,
};

const MODE_LABELS = {
  auto: '全自动',
  semi_auto: '半自动',
  disabled: '关闭',
};

const REASON_LABELS = {
  manual_conflict: '检测到人工操作，已转待审',
  focus_failed: '聚焦微信失败，已转待审',
  send_failed: '发送失败，已转待审',
};

const MODE_DISABLED = 'disabled';

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
    if (botState.status.global_settings) {
      botState.globalSettings = botState.status.global_settings;
    }
  } catch {
    // ignore
  }
  renderBotControl();
}

function renderBotControl() {
  const status = botState.status;
  const btn = document.getElementById('botToggleBtn');
  const info = document.getElementById('botInfo');
  if (!btn || !info) return;

  btn.textContent = status.running ? 'STOP' : 'START';
  btn.className = status.running ? 'btn btn-danger' : 'btn btn-primary';

  const uptime = status.running ? Math.floor(status.uptime) : 0;
  const uptimeStr = uptime > 60 ? `${Math.floor(uptime / 60)}m ${uptime % 60}s` : `${uptime}s`;
  const takeover = botState.globalSettings.enabled
    ? `全部托管: ${MODE_LABELS[botState.globalSettings.mode] || botState.globalSettings.mode}`
    : '全部托管: 关闭';
  const parts = [status.running ? `运行中 ${uptimeStr}` : '已停止'];
  parts.push(`会话 ${status.active_conversations}`);
  parts.push(takeover);
  if (status.pending_replies > 0) parts.push(`待审 ${status.pending_replies}`);
  info.textContent = parts.join(' | ');

  renderGlobalTakeover();
}

async function loadContactSettings() {
  try {
    const [contactSettings, globalSettings] = await Promise.all([
      fetchBotSettings(),
      fetchBotGlobalSettings(),
    ]);
    botState.contactSettings = {};
    for (const setting of contactSettings) {
      botState.contactSettings[setting.wxid] = setting;
    }
    botState.globalSettings = globalSettings;
  } catch {
    // ignore
  }
}

function getContactMode(wxid) {
  const setting = botState.contactSettings[wxid];
  if (setting) {
    if (!setting.enabled) return MODE_DISABLED;
    return setting.mode || 'semi_auto';
  }
  if (!botState.globalSettings.enabled) return MODE_DISABLED;
  return botState.globalSettings.mode || 'semi_auto';
}

function getContactModeSource(conv) {
  if (conv?.mode_source === 'contact') return '会话覆写';
  if (conv?.mode_source === 'global') return '跟随全局';
  return botState.contactSettings[conv?.wxid] ? '会话覆写' : '跟随全局';
}

async function setContactMode(wxid, mode) {
  const enabled = mode !== MODE_DISABLED;
  const actualMode = mode === MODE_DISABLED ? 'semi_auto' : mode;
  try {
    const result = await updateBotSettings(wxid, actualMode, enabled);
    botState.contactSettings[wxid] = result;
  } catch {
    // ignore
  }
  renderConversations();
}

async function setGlobalTakeover(enabled, mode = botState.globalSettings.mode) {
  const actualMode = mode === MODE_DISABLED ? 'semi_auto' : mode;
  try {
    botState.globalSettings = await updateBotGlobalSettings(actualMode, enabled);
  } catch {
    // ignore
  }
  renderBotControl();
  renderConversations();
}

function renderGlobalTakeover() {
  const mount = document.getElementById('botGlobalTakeover');
  if (!mount) return;

  const effectiveMode = botState.globalSettings.enabled
    ? botState.globalSettings.mode || 'semi_auto'
    : MODE_DISABLED;

  mount.innerHTML = `
    <div class="bot-global-card">
      <div class="bot-global-copy">
        <div class="bot-global-title">一键托管全部会话</div>
      </div>
      <label class="bot-global-switch">
        <span>启用</span>
        <div class="toggle ${botState.globalSettings.enabled ? 'on' : ''}" id="botGlobalEnabled"></div>
      </label>
      <select class="form-select bot-global-select" id="botGlobalMode">
        <option value="auto" ${effectiveMode === 'auto' ? 'selected' : ''}>全自动回复</option>
        <option value="semi_auto" ${effectiveMode === 'semi_auto' ? 'selected' : ''}>半自动待审</option>
        <option value="disabled" ${effectiveMode === MODE_DISABLED ? 'selected' : ''}>关闭托管</option>
      </select>
    </div>
  `;

  const toggle = document.getElementById('botGlobalEnabled');
  const select = document.getElementById('botGlobalMode');
  toggle.addEventListener('click', async () => {
    const nextEnabled = !botState.globalSettings.enabled;
    const selectedMode = select.value;
    await setGlobalTakeover(nextEnabled && selectedMode !== MODE_DISABLED, selectedMode);
  });
  select.addEventListener('change', async () => {
    const enabled = select.value !== MODE_DISABLED;
    await setGlobalTakeover(enabled, select.value);
  });
}

async function loadConversations() {
  try {
    botState.conversations = await fetchBotConversations();
  } catch {
    // ignore
  }
  renderConversations();
}

function renderConversations() {
  const list = document.getElementById('convList');
  if (!list) return;

  if (botState.conversations.length === 0) {
    list.innerHTML = '<div class="conv-empty">暂无会话</div>';
    return;
  }

  list.innerHTML = botState.conversations
    .map((conv) => {
      const selected = conv.wxid === botState.selectedWxid ? ' selected' : '';
      const pending = conv.pending_reply ? ' has-pending' : '';
      const badge = conv.pending_reply ? '<div class="conv-badge"></div>' : '';
      const mode = conv.effective_mode || getContactMode(conv.wxid);
      const modeClass = mode === MODE_DISABLED ? 'mode-off' : `mode-${mode}`;
      const source = getContactModeSource(conv);
      const pendingReason = conv.pending_reply?.reason
        ? `<div class="conv-reason">${escHtml(reasonLabel(conv.pending_reply.reason))}</div>`
        : '';
      return `<div class="conv-item${selected}${pending}" data-wxid="${escHtml(conv.wxid)}">
        <div class="conv-avatar">${(conv.nickname || conv.wxid)[0].toUpperCase()}</div>
        <div class="conv-info">
          <div class="conv-name">${escHtml(conv.nickname || conv.wxid)}</div>
          <div class="conv-preview">${conv.last_message_time || ''} | ${conv.message_count} 条 | ${source}</div>
          ${pendingReason}
        </div>
        <div class="conv-mode-wrap">
          <select class="conv-mode-select ${modeClass}" data-wxid="${escHtml(conv.wxid)}">
            <option value="auto" ${mode === 'auto' ? 'selected' : ''}>全自动</option>
            <option value="semi_auto" ${mode === 'semi_auto' ? 'selected' : ''}>半自动</option>
            <option value="disabled" ${mode === MODE_DISABLED ? 'selected' : ''}>关闭</option>
          </select>
        </div>
        ${badge}
      </div>`;
    })
    .join('');

  list.querySelectorAll('.conv-item').forEach((el) => {
    el.addEventListener('click', (event) => {
      if (event.target.tagName !== 'SELECT' && event.target.tagName !== 'OPTION') {
        selectConversation(el.dataset.wxid);
      }
    });
  });

  list.querySelectorAll('.conv-mode-select').forEach((select) => {
    select.addEventListener('change', (event) => {
      event.stopPropagation();
      setContactMode(select.dataset.wxid, select.value);
    });
  });
}

async function selectConversation(wxid) {
  botState.selectedWxid = wxid;
  renderConversations();
  await loadMessages(wxid);
  renderReplyPanel();
}

async function loadMessages(wxid) {
  try {
    botState.messages[wxid] = await fetchBotMessages(wxid);
  } catch {
    // ignore
  }
  renderMessages();
}

function renderMessages() {
  const thread = document.getElementById('msgThread');
  if (!thread) return;

  const wxid = botState.selectedWxid;
  const messages = botState.messages[wxid] || [];

  if (!wxid || messages.length === 0) {
    thread.innerHTML = `<div class="msg-empty">${!wxid ? '选择一个会话开始查看消息' : '暂无消息记录'}</div>`;
    return;
  }

  thread.innerHTML = messages
    .map((message) => {
      const side = message.is_from_customer ? 'customer' : 'self';
      const sender = message.is_from_customer ? '客户' : '我方';
      const reason = message.reply_status_reason
        ? `<div class="msg-reason">${escHtml(reasonLabel(message.reply_status_reason))}</div>`
        : '';
      return `<div class="msg-bubble ${side}">
        <div class="msg-meta"><span class="msg-sender">${sender}</span><span class="msg-time">${escHtml(message.timestamp)}</span></div>
        <div class="msg-content">${escHtml(message.content)}</div>
        ${reason}
      </div>`;
    })
    .join('');

  thread.scrollTop = thread.scrollHeight;
}

function renderReplyPanel() {
  const panel = document.getElementById('replyPanel');
  if (!panel) return;

  const wxid = botState.selectedWxid;
  const conv = botState.conversations.find((item) => item.wxid === wxid);
  const pending = conv?.pending_reply;

  if (!pending || pending.reply_status !== 'pending') {
    panel.innerHTML = '<div class="reply-empty">无待审批回复</div>';
    return;
  }

  const reasonHint = pending.reason
    ? `<div class="reply-hint">${escHtml(reasonLabel(pending.reason))}</div>`
    : '';

  panel.innerHTML = `
    <div class="reply-header">AI 建议回复</div>
    ${reasonHint}
    <div class="reply-original">
      <div class="reply-label">客户消息</div>
      <div class="reply-text">${escHtml(pending.content)}</div>
    </div>
    <div class="reply-suggestion">
      <div class="reply-label">AI 建议</div>
      <textarea class="reply-textarea" id="replyEdit" rows="4">${escHtml(pending.reply)}</textarea>
    </div>
    <div class="reply-actions">
      <button class="btn btn-primary" id="btnApprove">批准发送</button>
      <button class="btn btn-danger" id="btnReject">拒绝</button>
    </div>
  `;

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

function connectBotSSE() {
  if (botState.sseSource) botState.sseSource.close();
  botState.sseSource = new EventSource('/api/bot/stream');
  botState.sseSource.onmessage = (event) => {
    try {
      handleBotEvent(JSON.parse(event.data));
    } catch {
      // ignore
    }
  };
}

function handleBotEvent(data) {
  if (
    data.type === 'bot.status_change' ||
    data.type === 'bot.global_settings_updated' ||
    data.type === 'bot.contact_settings_updated'
  ) {
    refreshBotStatus();
    loadContactSettings().then(() => renderConversations());
  }
  if (
    data.type === 'bot.new_message' ||
    data.type === 'bot.reply_generated' ||
    data.type === 'bot.reply_sent' ||
    data.type === 'bot.reply_rejected' ||
    data.type === 'bot.reply_send_started' ||
    data.type === 'bot.reply_send_deferred' ||
    data.type === 'bot.reply_send_failed'
  ) {
    loadConversations();
    if (botState.selectedWxid === data.wxid) {
      loadMessages(botState.selectedWxid);
      renderReplyPanel();
    }
  }
}

function reasonLabel(reason) {
  return REASON_LABELS[reason] || reason;
}

export async function initBotPanel() {
  await refreshBotStatus();
  await loadContactSettings();
  await loadConversations();
  renderBotControl();
  connectBotSSE();

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
