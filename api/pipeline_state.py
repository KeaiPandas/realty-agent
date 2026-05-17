"""管道运行状态管理 — 活跃任务、历史记录、状态追踪"""
import asyncio
import time
from collections import deque
from typing import Optional

_active_runs: dict[str, asyncio.Task] = {}
_run_history: deque[dict] = deque(maxlen=50)
_run_state: dict[str, dict] = {}


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def update_run(run_id: str, **kwargs):
    if run_id not in _run_state:
        _run_state[run_id] = {
            "id": run_id, "contact": "", "contact_name": "",
            "status": "running",
            "steps": {}, "startTime": "", "endTime": "",
            "error": "", "message": "",
        }
    _run_state[run_id].update(kwargs)
    if len(_run_state) > 100:
        oldest = list(_run_state.keys())[0]
        _run_state.pop(oldest, None)


def finish_run(run_id: str, status: str, message: str = ""):
    _run_history.append({
        "run_id": run_id,
        "status": status,
        "message": message,
        "finished_at": now(),
    })
    _active_runs.pop(run_id, None)


def register_run(run_id: str, task: asyncio.Task):
    _active_runs[run_id] = task


def get_active_task(run_id: str) -> Optional[asyncio.Task]:
    return _active_runs.get(run_id)


def has_running() -> bool:
    return any(not t.done() for t in _active_runs.values())


def get_runs_list() -> list[dict]:
    runs = list(_run_state.values())
    runs.sort(key=lambda r: r.get("startTime", ""), reverse=True)
    return runs


def get_last_run() -> Optional[dict]:
    return _run_history[-1] if _run_history else None


def get_running_ids() -> list[str]:
    return [rid for rid, t in _active_runs.items() if not t.done()]


def is_run_active(run_id: str) -> bool:
    return run_id in _run_state and _run_state[run_id].get("status") == "running"


def get_run_steps(run_id: str) -> dict:
    return _run_state.get(run_id, {}).get("steps", {})
