// Backend API calls
import { API } from './state.js';

export async function fetchRuns() {
  const resp = await fetch(API + '/api/workflow/runs');
  if (!resp.ok) return null;
  return resp.json();
}

export async function fetchContacts() {
  const resp = await fetch(API + '/api/workflow/contacts');
  if (!resp.ok) return null;
  return resp.json();
}

export async function fetchDecrypt() {
  return fetch(API + '/api/workflow/decrypt').then(r => r.json());
}

export async function startPipelineAPI(body) {
  const resp = await fetch(API + '/api/workflow/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  return { ok: resp.ok, data };
}

export async function stopPipelineAPI(runId) {
  const resp = await fetch(API + '/api/workflow/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    console.warn('停止响应:', err.detail || resp.status);
  }
}

export async function fetchLogs(limit = 200) {
  const resp = await fetch(API + '/api/logs?limit=' + limit);
  if (!resp.ok) return null;
  return resp.json();
}

export async function fetchHealth() {
  return fetch(API + '/api/health').then(r => r.json());
}

export async function fetchSchedulerTasks() {
  return fetch(API + '/api/scheduler/tasks').then(r => r.json());
}

export async function createSchedulerTask(task) {
  const resp = await fetch(API + '/api/scheduler/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || '创建失败');
  }
  return resp.json();
}

export async function deleteSchedulerTask(id) {
  await fetch(API + '/api/scheduler/tasks/' + id, { method: 'DELETE' });
}

export async function toggleSchedulerTask(id, enabled) {
  await fetch(API + '/api/scheduler/tasks/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}
