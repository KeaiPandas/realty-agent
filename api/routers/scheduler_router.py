"""定时任务 CRUD 路由"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.scheduler import scheduler_manager

router = APIRouter()


class TaskCreate(BaseModel):
    task_id: str
    cron: str
    contact_id: str
    date: Optional[str] = ""
    date_start: Optional[str] = ""
    date_end: Optional[str] = ""
    scan_mode: Optional[str] = "today"
    enabled: Optional[bool] = True


class TaskUpdate(BaseModel):
    enabled: Optional[bool] = None
    cron: Optional[str] = None
    contact_id: Optional[str] = None
    date: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    scan_mode: Optional[str] = None


@router.get("/tasks")
async def list_tasks():
    return {"tasks": scheduler_manager.list_tasks()}


@router.post("/tasks")
async def create_task(req: TaskCreate):
    if req.task_id in scheduler_manager._tasks:
        raise HTTPException(409, f"任务 {req.task_id} 已存在")
    task = scheduler_manager.create_task(
        req.task_id, req.cron, req.contact_id, req.date or "",
        req.date_start or "", req.date_end or "",
        req.scan_mode or "today", req.enabled,
    )
    return task


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "无更新内容")
    result = scheduler_manager.update_task(task_id, **updates)
    if not result:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return result


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    if task_id not in scheduler_manager._tasks:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    scheduler_manager.delete_task(task_id)
    return {"status": "deleted"}
