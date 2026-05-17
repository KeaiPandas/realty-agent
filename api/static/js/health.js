// Health check
import { fetchHealth } from './api.js';

export async function refreshHealth() {
  const names = { wechat_process: '微信进程', wechat_db: '微信数据库', feishu: '飞书同步', llm: 'LLM 接口' };
  try {
    const data = await fetchHealth();
    const grid = document.getElementById('healthGrid');
    grid.innerHTML = '';
    Object.entries(data.checks).forEach(([key, check], i) => {
      const card = document.createElement('div');
      card.className = 'health-card ' + check.status;
      card.style.animationDelay = i * 0.1 + 's';
      card.innerHTML = '<div class="health-icon"></div><div><div class="health-name">' + (names[key] || key) + '</div><div class="health-msg">' + check.message + '</div></div>';
      grid.appendChild(card);
    });
  } catch (e) { console.warn('健康检查失败', e); }
}
