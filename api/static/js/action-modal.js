// Action modal — AI generates reply, human reviews and sends via Bot
// Fetches real AI-generated reply from backend

import { sendManualMessage } from './api.js';

// Fallback mock data (used when API fails)
const MOCK_ACTIONS = {
  1: { name: '李四', wxid: 'wxid_li', desc: '"有三居吗？" → 推荐嘎洒 89㎡ 三居',
       draft: '李四您好！我们嘎洒项目有 89㎡ 三居户型，南北通透，总价比您预期还低一些。我给您发个户型图看看？方便的话可以安排实地看房 🏠' },
  2: { name: '王五', wxid: 'wxid_wang', desc: '沉默 12 天，确认本周是否来版纳',
       draft: '王哥您好！好久没联系了，您之前说本周要来版纳看房，行程定了吗？我帮您安排一下接待 🚗' },
  3: { name: '张三', wxid: 'wxid_zhang', desc: '7 天未回复，发送带看邀请',
       draft: '张哥，嘎洒那边新开了一期，户型和价格都很有优势。您看周末方便的话过来实地看看？我帮您安排接送 🌴' },
  4: { name: '赵六', wxid: 'wxid_zhao', desc: '发送嘎栋项目资料 + 户型图',
       draft: '赵总，嘎栋项目的户型图和价格表给您整理好了，您看看哪个户型感兴趣，我再帮您算一下具体方案 📋' },
  5: { name: '钱七', wxid: 'wxid_qian', desc: '14 天未联系，发问候消息',
       draft: '钱哥好！最近忙什么呢？之前看的那几个项目有新的优惠活动了，您有兴趣了解一下吗？随时联系我 😊' },
};

let currentAction = null;

export async function openActionModal(actionId) {
  const overlay = document.getElementById('actionModal');
  overlay.style.display = 'flex';

  const customerEl = document.getElementById('actionCustomer');
  const situationEl = document.getElementById('actionSituation');
  const draftEl = document.getElementById('actionDraft');
  const statusEl = document.getElementById('actionStatus');

  // Show loading state
  customerEl.textContent = '加载中...';
  situationEl.textContent = '';
  draftEl.value = '';
  statusEl.textContent = 'AI 生成话术中...';
  statusEl.style.color = 'var(--gold)';

  // Try fetching from API
  try {
    const resp = await fetch(`/api/leads/actions/${actionId}/generate-reply`, { method: 'POST' });
    if (resp.ok) {
      const data = await resp.json();
      currentAction = {
        _actionId: actionId,
        name: data.nickname || data.name || '客户',
        wxid: data.wxid,
        desc: data.desc || '',
        draft: data.draft || '',
      };
      customerEl.textContent = currentAction.name;
      situationEl.textContent = currentAction.desc;
      draftEl.value = currentAction.draft;
      statusEl.textContent = '✓ AI 已生成话术，可编辑后发送';
      statusEl.style.color = 'var(--green)';
      return;
    }
  } catch {}

  // API failed — show empty state
  currentAction = { _actionId: actionId, name: '客户', wxid: '', desc: '', draft: '' };
  customerEl.textContent = '客户';
  situationEl.textContent = '无法获取数据';
  draftEl.value = '';
  statusEl.textContent = '后端未连接，请检查服务是否启动';
  statusEl.style.color = 'var(--red)';
}

export function closeActionModal() {
  document.getElementById('actionModal').style.display = 'none';
  currentAction = null;
}

export async function sendActionReply() {
  if (!currentAction) return;

  const text = document.getElementById('actionDraft').value.trim();
  if (!text) return;

  const btn = document.getElementById('actionSendBtn');
  const status = document.getElementById('actionStatus');
  btn.classList.add('btn-loading');
  btn.disabled = true;
  status.textContent = '发送中...';
  status.style.color = 'var(--text-muted)';

  try {
    const result = await sendManualMessage(currentAction.wxid, text);
    if (result.status === 'sent') {
      status.textContent = '✓ 已发送';
      status.style.color = 'var(--green)';
      // Mark action as done in dashboard
      if (window._completeActionById) {
        window._completeActionById(currentAction.wxid);
      }
      setTimeout(() => closeActionModal(), 1500);
    } else {
      status.textContent = '发送失败: ' + (result.error || '未知错误');
      status.style.color = 'var(--red)';
    }
  } catch {
    status.textContent = '发送失败，后端未连接';
    status.style.color = 'var(--red)';
  }

  btn.classList.remove('btn-loading');
  btn.disabled = false;
}

export async function regenerateDraft() {
  if (!currentAction) return;

  const status = document.getElementById('actionStatus');
  const textarea = document.getElementById('actionDraft');
  status.textContent = 'AI 重新生成中...';
  status.style.color = 'var(--gold)';

  // Try re-calling the API for a fresh generation
  try {
    // Find the action ID from current context — look it up from the action card
    const actionCard = document.querySelector(`.action-card[data-id]`);
    // Since we don't have the actionId stored, we use the current draft as context
    // Simply call the LLM again with variation by appending a regeneration hint
    const resp = await fetch('/api/leads/actions/' + currentAction._actionId + '/generate-reply?force=true', {
      method: 'POST',
    });
    if (resp.ok) {
      const data = await resp.json();
      textarea.value = data.draft || textarea.value;
      status.textContent = '✓ 已重新生成';
      status.style.color = 'var(--green)';
      return;
    }
  } catch {}

  // API failed
  status.textContent = '重新生成失败，请检查后端连接';
  status.style.color = 'var(--red)';
}

// Expose
window._openActionModal = openActionModal;
window._closeActionModal = closeActionModal;
window._sendActionReply = sendActionReply;
window._regenerateDraft = regenerateDraft;
