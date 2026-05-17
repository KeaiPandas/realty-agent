// SSE connection and event dispatch
import { API, state, pipelineRuns, getContactName, setPipelineRunning, renderTaskList } from './state.js';
import { addLogCard, updateLogCard, filterLogs } from './logs.js';

let evtSource = null;

export function connectSSE() {
  evtSource = new EventSource(API + '/api/logs/stream');
  evtSource.onopen = () => {
    document.getElementById('connDot').classList.add('connected');
    document.getElementById('connText').textContent = 'connected';
  };
  evtSource.onerror = () => {
    document.getElementById('connDot').classList.remove('connected');
    document.getElementById('connText').textContent = 'reconnecting...';
  };
  evtSource.onmessage = (e) => {
    handleEvent(JSON.parse(e.data));
  };
}

function handleEvent(data) {
  if (data.type === 'tool_start' || data.type === 'pipeline_start') {
    addLogCard(data);
  }
  if (data.type === 'tool_end' || data.type === 'tool_error') {
    updateLogCard(data);
  }
  if (data.type === 'pipeline_progress') {
    addLogCard({
      id: 'prog-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
      tool: 'pipeline_progress',
      run_id: data.run_id || state.currentRunId || '',
      status: 'running',
      input: data.message || '',
      timestamp: data.timestamp || '',
    });
  }
  if (data.type === 'pipeline_end') {
    addLogCard({
      id: 'pipe-end-' + (data.run_id || state.currentRunId || ''),
      tool: 'pipeline_end',
      run_id: data.run_id || state.currentRunId || '',
      status: data.status === 'failed' ? 'error' : 'success',
      output: data.message || data.error || (data.status === 'failed' ? '失败' : '完成'),
      timestamp: data.timestamp || '',
    });
  }

  if (data.type === 'pipeline_start') {
    state.currentRunId = data.run_id;
    state.selectedRunId = data.run_id;
    const contactName = data.contact_id === '__all__' ? '所有人' : getContactName(data.contact_id);
    pipelineRuns[data.run_id] = {
      id: data.run_id,
      contact: data.contact_id,
      contact_name: contactName,
      status: 'running',
      steps: {},
      startTime: data.timestamp || new Date().toLocaleString('zh-CN'),
      endTime: '',
      error: '',
      message: '',
      stepOutputs: {},
    };
    setPipelineRunning(true, data.contact_id);
    renderTaskList();
    filterLogs();
  }
  if (data.type === 'tool_start' && state.currentRunId && pipelineRuns[state.currentRunId]) {
    pipelineRuns[state.currentRunId].steps[data.tool] = 'active';
    pipelineRuns[state.currentRunId].stepOutputs[data.tool] = data.input || '';
    renderTaskList();
  }
  if (data.type === 'tool_end' && state.currentRunId && pipelineRuns[state.currentRunId]) {
    pipelineRuns[state.currentRunId].steps[data.tool] = 'done';
    pipelineRuns[state.currentRunId].stepOutputs[data.tool] = data.output || '';
    renderTaskList();
  }
  if (data.type === 'tool_error' && state.currentRunId && pipelineRuns[state.currentRunId]) {
    pipelineRuns[state.currentRunId].steps[data.tool] = 'failed';
    pipelineRuns[state.currentRunId].stepOutputs[data.tool] = data.error || '';
    renderTaskList();
  }
  if (data.type === 'pipeline_end') {
    if (state.currentRunId && pipelineRuns[state.currentRunId]) {
      const run = pipelineRuns[state.currentRunId];
      run.status = data.status === 'failed' ? 'failed' : 'completed';
      run.endTime = new Date().toLocaleString('zh-CN');
      run.error = data.error || '';
      run.message = data.message || '';
    }
    setPipelineRunning(false);
    renderTaskList();
  }
  if (data.type === 'pipeline_progress') {
    if (state.currentRunId && pipelineRuns[state.currentRunId]) {
      pipelineRuns[state.currentRunId].message = data.message || '';
      renderTaskList();
    }
  }
}
