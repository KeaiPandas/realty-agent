// Task list rendering — running/history tabs
import { state, pipelineRuns, STEPS, STEP_LABELS, escHtml, getContactName, stopRun as doStopRun, filterLogs } from './state.js';

export function switchTaskTab(tab, el) {
  state.currentTaskTab = tab;
  document.querySelectorAll('.task-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderTaskList();
}

export function renderTaskList() {
  const container = document.getElementById('taskList');
  const allRuns = Object.values(pipelineRuns).reverse();
  const running = allRuns.filter(r => r.status === 'running');
  const history = allRuns.filter(r => r.status !== 'running');

  document.getElementById('taskRunningCount').textContent = running.length;
  document.getElementById('taskHistoryCount').textContent = history.length;

  const display = state.currentTaskTab === 'running' ? running : history;

  if (display.length === 0) {
    const msg = state.currentTaskTab === 'running' ? '暂无运行中的任务' : '暂无历史任务';
    container.innerHTML = '<div class="task-empty">' + msg + '</div>';
    return;
  }

  container.innerHTML = '';
  display.forEach(run => {
    const card = document.createElement('div');
    card.className = 'task-card ' + run.status;
    if (run.id === state.selectedRunId) card.className += ' selected';
    card.style.cursor = 'pointer';
    card.setAttribute('data-run-id', run.id);
    card.onclick = (e) => {
      if (e.target.tagName === 'BUTTON') return;
      selectRun(run.id);
    };

    let contactDisplay = run.contact_name || '';
    if (!contactDisplay) {
      contactDisplay = run.contact === '__all__' ? '所有人' : getContactName(run.contact);
    }

    let stepsHtml = '<div class="task-steps">';
    STEPS.forEach(step => {
      const s = run.steps[step] || '';
      stepsHtml += '<div class="task-step-dot ' + s + '" title="' + STEP_LABELS[step] + '"></div>';
    });
    stepsHtml += '</div>';

    let detailsHtml = '';
    const doneSteps = STEPS.filter(s => run.steps[s] === 'done' && run.stepOutputs && run.stepOutputs[s]);
    if (doneSteps.length > 0) {
      detailsHtml += '<div class="task-detail-item"><span class="value">' + escHtml(run.stepOutputs[doneSteps[doneSteps.length - 1]]) + '</span></div>';
    }
    const activeStep = STEPS.find(s => run.steps[s] === 'active');
    if (activeStep) {
      detailsHtml += '<div class="task-detail-item"><span class="label">当前:</span><span class="value">' + STEP_LABELS[activeStep] + '</span></div>';
    }
    if (state.currentTaskTab === 'history') {
      if (run.startTime) detailsHtml += '<div class="task-detail-item"><span class="label">开始:</span><span class="value">' + escHtml(run.startTime) + '</span></div>';
      if (run.endTime) detailsHtml += '<div class="task-detail-item"><span class="label">结束:</span><span class="value">' + escHtml(run.endTime) + '</span></div>';
    }

    let msgHtml = '';
    if (run.status === 'running' && run.message) {
      msgHtml = '<div class="task-card-msg">' + escHtml(run.message) + '</div>';
    } else if (run.status === 'completed') {
      msgHtml = '<div class="task-card-msg">' + escHtml(run.message || '已完成') + '</div>';
    } else if (run.status === 'failed') {
      msgHtml = '<div class="task-card-msg" style="color:var(--coral)">' + escHtml(run.error || '未知错误') + '</div>';
    }

    const badgeLabel = run.status === 'running' ? '运行中' : run.status === 'completed' ? '完成' : '失败';

    card.innerHTML =
      '<div class="task-card-top">' +
        '<div class="task-card-title">' +
          '<span class="task-contact">' + escHtml(contactDisplay) + '</span>' +
          '<span class="task-id">#' + run.id + '</span>' +
        '</div>' +
        '<div class="task-card-actions">' +
          '<span class="task-badge ' + run.status + '">' + badgeLabel + '</span>' +
          (run.status === 'running' ? '<button class="btn-stop" onclick="event.stopPropagation();_stopRun(\'' + run.id + '\')">停止</button>' : '') +
        '</div>' +
      '</div>' +
      stepsHtml +
      '<div class="task-detail">' + detailsHtml + '</div>' +
      msgHtml;

    container.appendChild(card);
  });
}

function selectRun(runId) {
  state.selectedRunId = runId;
  renderTaskList();
  filterLogs();
}
