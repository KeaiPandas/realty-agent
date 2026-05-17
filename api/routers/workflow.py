"""工作流控制 — 启动/停止管道、联系人列表、解密"""
import asyncio
import json
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters.db_layout import get_contact_db
from api.tool_logger import log_step, log_step_end, log_pipeline_event
from config import settings

router = APIRouter()

_active_runs: dict[str, asyncio.Task] = {}
_run_history: deque[dict] = deque(maxlen=50)
_decrypted_db_paths: dict = {}
_run_state: dict[str, dict] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _update_run_state(run_id: str, **kwargs):
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


class PipelineRequest(BaseModel):
    contact_id: str
    date: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    parse_only: bool = False


def _do_decrypt() -> dict:
    """执行完整的数据库解密"""
    from adapters.decrypt import decrypt_all_databases
    return decrypt_all_databases()


def _ensure_decrypted() -> dict:
    """确保有解密后的数据库可用"""
    global _decrypted_db_paths
    if _decrypted_db_paths and get_contact_db(_decrypted_db_paths):
        return _decrypted_db_paths
    result = _do_decrypt()
    _decrypted_db_paths = result
    return result


@router.get("/decrypt")
async def decrypt_databases():
    """触发数据库解密，返回解密状态"""
    try:
        result = await asyncio.to_thread(_do_decrypt)
        _decrypted_db_paths = result
        return {"status": "ok", "databases": list(result.keys())}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/start")
async def start_pipeline(req: PipelineRequest):
    if _active_runs:
        running = [rid for rid, t in _active_runs.items() if not t.done()]
        if running:
            raise HTTPException(409, "已有管道正在运行，请等待完成后再启动")
    run_id = str(uuid.uuid4())[:8]
    task = asyncio.create_task(_execute_pipeline(run_id, req))
    _active_runs[run_id] = task
    return {"run_id": run_id, "status": "started"}


@router.post("/stop")
async def stop_pipeline(req: dict):
    run_id = req.get("run_id", "")
    now = _now()
    task = _active_runs.get(run_id)
    if task and not task.done():
        task.cancel()
        del _active_runs[run_id]
        _update_run_state(run_id, status="completed", message="已停止", endTime=now)
        _finish_run(run_id, "completed", "已停止")
        return {"status": "cancelled"}
    if run_id in _run_state and _run_state[run_id].get("status") == "running":
        _update_run_state(run_id, status="completed", message="任务已结束", endTime=now)
        _finish_run(run_id, "completed", "任务已结束")
        return {"status": "stopped"}
    raise HTTPException(404, f"运行 {run_id} 不存在或已结束")


@router.get("/status")
async def pipeline_status():
    current = None
    for rid, task in _active_runs.items():
        if not task.done():
            current = {"run_id": rid, "status": "running"}
    last = _run_history[-1] if _run_history else None
    return {"current_run": current, "last_run": last}


@router.get("/runs")
async def list_runs():
    runs = list(_run_state.values())
    runs.sort(key=lambda r: r.get("startTime", ""), reverse=True)
    return {"runs": runs}


@router.get("/contacts")
async def list_contacts():
    try:
        db_paths = await asyncio.to_thread(_ensure_decrypted)
        if not get_contact_db(db_paths):
            raise HTTPException(500, "联系人数据库未解密，请先点击解密")
        from adapters.extract import get_dm_contacts_with_messages
        contacts = await asyncio.to_thread(get_dm_contacts_with_messages, db_paths)
        return contacts[:settings.LIST_CONTACTS_LIMIT]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"获取联系人失败: {e}")


def _resolve_contact_name(contact_id: str) -> str:
    """Resolve wxid to display name from decrypted database"""
    if contact_id == "__all__":
        return "所有人"
    try:
        db_paths = _decrypted_db_paths or {}
        contact_db = get_contact_db(db_paths)
        if contact_db:
            from adapters.extract import get_contact_nicknames
            nicknames = get_contact_nicknames(contact_db)
            if nicknames.get(contact_id):
                return nicknames[contact_id]
    except Exception:
        pass
    return contact_id


async def _execute_pipeline(run_id: str, req: PipelineRequest):
    if req.contact_id == "__all__":
        await _execute_pipeline_all(run_id, req)
        return

    contact_name = await asyncio.to_thread(_resolve_contact_name, req.contact_id)
    log_pipeline_event("pipeline_start", run_id=run_id, contact_id=req.contact_id)
    _update_run_state(run_id, contact=req.contact_id, contact_name=contact_name,
                      status="running", startTime=_now(),
                      steps={}, error="", message="")

    try:
        # Step 1: 解密
        eid = log_step("decrypt_db", run_id, input=f"contact={req.contact_id}")
        _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "decrypt_db": "active"})
        try:
            db_paths = await asyncio.to_thread(_ensure_decrypted)
            log_step_end(eid, output=f"解密 {len(db_paths)} 个数据库")
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "decrypt_db": "done"})
        except Exception as e:
            log_step_end(eid, error=str(e))
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "decrypt_db": "failed"})
            raise

        # Step 2: 提取消息
        date_desc = req.date_start and req.date_end and f"{req.date_start}~{req.date_end}" or req.date or "全部"
        eid = log_step("extract_dm", run_id, input=f"wxid={req.contact_id}, date={date_desc}")
        _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "extract_dm": "active"})
        try:
            from adapters.extract import extract_dm_messages, format_dm_messages
            messages = await asyncio.to_thread(
                extract_dm_messages, db_paths, req.contact_id,
                req.date, req.date_start, req.date_end,
            )
            chat_content = format_dm_messages(req.contact_id, messages, date_desc)
            log_step_end(eid, output=f"提取 {len(messages)} 条消息")
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "extract_dm": "done"},
                              message=f"提取 {len(messages)} 条消息")
        except Exception as e:
            log_step_end(eid, error=str(e))
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "extract_dm": "failed"})
            raise

        if not messages:
            log_pipeline_event("pipeline_end", run_id=run_id, status="completed",
                               message="无消息")
            _finish_run(run_id, "completed", "无消息")
            return

        # Step 3: AI解析
        eid = log_step("parse_profile", run_id, input=f"{len(chat_content)} 字符")
        _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "parse_profile": "active"})
        try:
            from main import step_parse
            profile = await step_parse(chat_content)
            log_step_end(eid, output=f"提取 {sum(1 for v in profile.model_dump().values() if v is not None)} 个字段")
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "parse_profile": "done"})
        except Exception as e:
            log_step_end(eid, error=str(e))
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "parse_profile": "failed"})
            raise

        # 保存本地
        output_path = Path(__file__).parent.parent.parent / settings.DATA_DIR / f"profile_{req.contact_id}.json"
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(
            json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Step 4: 同步飞书
        if not req.parse_only:
            eid = log_step("sync_feishu", run_id, input=f"name={profile.name}")
            _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "sync_feishu": "active"})
            try:
                from main import step_sync_feishu
                result = await asyncio.to_thread(step_sync_feishu, profile)
                log_step_end(eid, output=f"action={result['action']}")
                _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "sync_feishu": "done"})
            except Exception as e:
                log_step_end(eid, error=str(e))
                _update_run_state(run_id, steps={**_run_state[run_id]["steps"], "sync_feishu": "failed"})
                raise

        log_pipeline_event("pipeline_end", run_id=run_id, status="completed")
        _update_run_state(run_id, status="completed", endTime=_now())
        _finish_run(run_id, "completed")

    except Exception as e:
        log_pipeline_event("pipeline_end", run_id=run_id, status="failed", error=str(e))
        _update_run_state(run_id, status="failed", error=str(e), endTime=_now())
        _finish_run(run_id, "failed", str(e))


async def _execute_pipeline_all(run_id: str, req: PipelineRequest):
    """批量逐个处理所有有消息的联系人，每条上限100"""
    log_pipeline_event("pipeline_start", run_id=run_id, contact_id="__all__")
    _update_run_state(run_id, contact="__all__", contact_name="所有人",
                      status="running", startTime=_now(),
                      steps={"decrypt_db": "active"}, error="", message="")

    try:
        # Step 1: 解密
        eid = log_step("decrypt_db", run_id, input="contact=__all__")
        try:
            db_paths = await asyncio.to_thread(_ensure_decrypted)
            log_step_end(eid, output=f"解密 {len(db_paths)} 个数据库")
            _update_run_state(run_id, steps={"decrypt_db": "done", "extract_dm": "active"})
        except Exception as e:
            log_step_end(eid, error=str(e))
            _update_run_state(run_id, steps={"decrypt_db": "failed"})
            raise

        # Step 2: 获取有实际消息的联系人
        from adapters.extract import get_dm_contacts_with_messages, extract_dm_messages, format_dm_messages
        contacts = await asyncio.to_thread(get_dm_contacts_with_messages, db_paths)
        total = len(contacts)
        log_pipeline_event("pipeline_progress", run_id=run_id,
                           message=f"共 {total} 个有消息的联系人，开始逐个处理")

        processed = 0
        skipped = 0
        failed = 0
        BATCH_LIMIT = 100
        task = asyncio.current_task()

        for idx, contact in enumerate(contacts, 1):
            if task and task.cancelled():
                log_pipeline_event("pipeline_end", run_id=run_id, status="completed",
                                   message=f"用户停止: 已处理 {processed}, 跳过 {skipped}, 失败 {failed}")
                _finish_run(run_id, "completed", f"用户停止于第 {idx}/{total} 个")
                return

            contact_id = contact["wxid"]
            display_name = contact.get("alias") or contact.get("nickname") or contact_id
            date_desc = req.date_start and req.date_end and f"{req.date_start}~{req.date_end}" or req.date or "全部"

            log_pipeline_event("pipeline_progress", run_id=run_id,
                               message=f"[{idx}/{total}] {display_name} — 提取消息中...")
            _update_run_state(run_id, message=f"[{idx}/{total}] {display_name} — 提取消息中...")

            try:
                messages = await asyncio.to_thread(
                    extract_dm_messages, db_paths, contact_id,
                    req.date, req.date_start, req.date_end,
                    limit=BATCH_LIMIT,
                )
            except Exception:
                failed += 1
                continue

            if not messages:
                skipped += 1
                continue

            chat_content = format_dm_messages(display_name, messages, date_desc)

            log_pipeline_event("pipeline_progress", run_id=run_id,
                               message=f"[{idx}/{total}] {display_name} — AI 解析中 ({len(messages)} 条)")
            _update_run_state(run_id, message=f"[{idx}/{total}] {display_name} — AI 解析中 ({len(messages)} 条)",
                              steps={"decrypt_db": "done", "extract_dm": "done", "parse_profile": "active", "sync_feishu": ""})

            try:
                from main import step_parse
                profile = await step_parse(chat_content)

                output_path = Path(__file__).parent.parent.parent / settings.DATA_DIR / f"profile_{contact_id}.json"
                output_path.parent.mkdir(exist_ok=True)
                output_path.write_text(
                    json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                if not req.parse_only:
                    from main import step_sync_feishu
                    await asyncio.to_thread(step_sync_feishu, profile)

                processed += 1
                log_pipeline_event("pipeline_progress", run_id=run_id,
                                   message=f"[{idx}/{total}] {display_name} — 完成 (累计 {processed} 个)")
                _update_run_state(run_id,
                                  message=f"[{idx}/{total}] {display_name} — 完成 (累计 {processed} 个)",
                                  steps={"decrypt_db": "done", "extract_dm": "done", "parse_profile": "done", "sync_feishu": "done"})
            except Exception:
                failed += 1

        summary = f"完成: {processed} 个解析成功, {skipped} 个无消息, {failed} 个失败"
        log_pipeline_event("pipeline_end", run_id=run_id, status="completed", message=summary)
        _update_run_state(run_id, status="completed", message=summary, endTime=_now())
        _finish_run(run_id, "completed", summary)

    except asyncio.CancelledError:
        log_pipeline_event("pipeline_end", run_id=run_id, status="completed",
                           message="用户手动停止")
        _update_run_state(run_id, status="completed", message="用户手动停止", endTime=_now())
        _finish_run(run_id, "completed", "用户手动停止")
    except Exception as e:
        log_pipeline_event("pipeline_end", run_id=run_id, status="failed", error=str(e))
        _update_run_state(run_id, status="failed", error=str(e), endTime=_now())
        _finish_run(run_id, "failed", str(e))


def _finish_run(run_id: str, status: str, message: str = ""):
    _run_history.append({
        "run_id": run_id,
        "status": status,
        "message": message,
        "finished_at": _now(),
    })
    _active_runs.pop(run_id, None)
