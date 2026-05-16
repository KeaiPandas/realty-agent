"""定时任务调度 — APScheduler 封装"""
import asyncio
import time
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

SCHEDULER_CONFIG = Path(__file__).parent.parent / "config" / "scheduler.yaml"


class SchedulerManager:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, dict] = {}
        self._load()

    def _load(self):
        if SCHEDULER_CONFIG.exists():
            data = yaml.safe_load(SCHEDULER_CONFIG.read_text(encoding="utf-8")) or {}
            self._tasks = data.get("tasks", {})

    def _save(self):
        SCHEDULER_CONFIG.parent.mkdir(exist_ok=True)
        SCHEDULER_CONFIG.write_text(
            yaml.dump({"tasks": self._tasks}, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    def start(self):
        self._scheduler.start()
        for task_id, task in self._tasks.items():
            if task.get("enabled", True):
                self._add_job(task_id, task)

    def shutdown(self):
        self._scheduler.shutdown(wait=False)

    def _add_job(self, task_id: str, task: dict):
        parts = task["cron"].split()
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
        )
        self._scheduler.add_job(
            _run_scheduled_pipeline, trigger, id=task_id,
            args=[task],
            replace_existing=True,
        )

    def create_task(self, task_id: str, cron: str, contact_id: str,
                    date: str = "", date_start: str = "", date_end: str = "",
                    scan_mode: str = "today", enabled: bool = True) -> dict:
        task = {
            "cron": cron,
            "contact_id": contact_id,
            "date": date,
            "date_start": date_start,
            "date_end": date_end,
            "scan_mode": scan_mode,
            "enabled": enabled,
        }
        self._tasks[task_id] = task
        if enabled:
            self._add_job(task_id, task)
        self._save()
        return task

    def delete_task(self, task_id: str):
        self._tasks.pop(task_id, None)
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass
        self._save()

    def update_task(self, task_id: str, **updates) -> dict | None:
        if task_id not in self._tasks:
            return None
        self._tasks[task_id].update(updates)
        task = self._tasks[task_id]
        if task.get("enabled", True):
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
            self._add_job(task_id, task)
        else:
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
        self._save()
        return task

    def list_tasks(self) -> dict:
        return self._tasks


def _resolve_dates(task: dict) -> tuple[str | None, str | None]:
    """根据 scan_mode 解析出 date_start / date_end"""
    mode = task.get("scan_mode", "today")
    if mode == "today":
        today = time.strftime("%Y-%m-%d")
        return today, today
    elif mode == "range" and task.get("date_start") and task.get("date_end"):
        return task["date_start"], task["date_end"]
    elif mode == "all":
        return None, None
    return None, None


def _run_scheduled_pipeline(task: dict):
    """APScheduler 调用的同步入口"""
    contact_id = task.get("contact_id", "")
    if not contact_id:
        return
    date_start, date_end = _resolve_dates(task)
    from api.routers.workflow import PipelineRequest
    req = PipelineRequest(
        contact_id=contact_id,
        date_start=date_start,
        date_end=date_end,
    )
    asyncio.run(_scheduled_async(req))


async def _scheduled_async(req):
    from api.routers.workflow import _execute_pipeline
    run_id = f"sched_{time.strftime('%H%M%S')}"
    await _execute_pipeline(run_id, req)


scheduler_manager = SchedulerManager()
