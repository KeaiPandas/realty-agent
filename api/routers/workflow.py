"""工作流控制 — HTTP 端点 + 管道执行编排"""
import asyncio
import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sync.db_layout import get_contact_db
from api.decrypt_coordinator import ensure_decrypted, get_decrypted_paths
from api.pipeline_state import (
    now, update_run, finish_run, register_run,
    get_active_task, has_running, get_runs_list, get_last_run, get_running_ids,
    is_run_active, get_run_steps,
)
from api.tool_logger import log_step, log_step_end, log_pipeline_event
from config import settings

router = APIRouter()


class PipelineRequest(BaseModel):
    contact_id: str
    date: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    parse_only: bool = False


# ── HTTP Endpoints ──


@router.get("/decrypt")
async def decrypt_databases():
    try:
        result = await asyncio.to_thread(ensure_decrypted)
        return {"status": "ok", "databases": list(result.keys())}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/start")
async def start_pipeline(req: PipelineRequest):
    if get_running_ids():
        raise HTTPException(409, "已有管道正在运行，请等待完成后再启动")
    run_id = str(uuid.uuid4())[:8]
    task = asyncio.create_task(_execute_pipeline(run_id, req))
    register_run(run_id, task)
    return {"run_id": run_id, "status": "started"}


@router.post("/stop")
async def stop_pipeline(req: dict):
    run_id = req.get("run_id", "")
    t = now()
    task = get_active_task(run_id)
    if task and not task.done():
        task.cancel()
        update_run(run_id, status="completed", message="已停止", endTime=t)
        finish_run(run_id, "completed", "已停止")
        return {"status": "cancelled"}
    if is_run_active(run_id):
        update_run(run_id, status="completed", message="任务已结束", endTime=t)
        finish_run(run_id, "completed", "任务已结束")
        return {"status": "stopped"}
    raise HTTPException(404, f"运行 {run_id} 不存在或已结束")


@router.get("/status")
async def pipeline_status():
    current = None
    if has_running():
        ids = get_running_ids()
        current = {"run_id": ids[0], "status": "running"}
    return {"current_run": current, "last_run": get_last_run()}


@router.get("/runs")
async def list_runs():
    return {"runs": get_runs_list()}


@router.get("/contacts")
async def list_contacts():
    try:
        db_paths = await asyncio.to_thread(ensure_decrypted)
        if not get_contact_db(db_paths):
            raise HTTPException(500, "联系人数据库未解密，请先点击解密")
        from services.sync.extract import get_dm_contacts_with_messages
        contacts = await asyncio.to_thread(get_dm_contacts_with_messages, db_paths)
        return contacts[:settings.LIST_CONTACTS_LIMIT]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"获取联系人失败: {e}")


# ── Pipeline Execution ──


def _resolve_contact_name(contact_id: str) -> str:
    if contact_id == "__all__":
        return "所有人"
    try:
        db_paths = get_decrypted_paths() or {}
        contact_db = get_contact_db(db_paths)
        if contact_db:
            from services.sync.extract import get_contact_nicknames
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
    update_run(run_id, contact=req.contact_id, contact_name=contact_name,
               status="running", startTime=now(),
               steps={}, error="", message="")

    try:
        # Step 1: 解密
        db_paths = await _run_step(run_id, "decrypt_db",
                                   lambda: ensure_decrypted(),
                                   f"contact={req.contact_id}",
                                   lambda r: f"解密 {len(r)} 个数据库")

        # Step 2: 提取消息
        date_desc = req.date_start and req.date_end and f"{req.date_start}~{req.date_end}" or req.date or "全部"
        from services.sync.extract import extract_dm_messages, format_dm_messages
        messages = await _run_step(run_id, "extract_dm",
                                   lambda: asyncio.to_thread(
                                       extract_dm_messages, db_paths, req.contact_id,
                                       req.date, req.date_start, req.date_end,
                                   ),
                                   f"wxid={req.contact_id}, date={date_desc}",
                                   lambda r: f"提取 {len(r)} 条消息",
                                   post_update=lambda r: update_run(run_id, message=f"提取 {len(r)} 条消息"))

        if not messages:
            log_pipeline_event("pipeline_end", run_id=run_id, status="completed", message="无消息")
            finish_run(run_id, "completed", "无消息")
            return

        # Step 2.5: 写入本地数据库
        from services.sync.persist import persist_messages, persist_profile as persist_profile_to_db
        from services.sync.db_layout import get_contact_db
        from services.sync.extract import get_contact_profiles
        contact_db = get_contact_db(db_paths)
        contact_profile = (get_contact_profiles(contact_db).get(req.contact_id) if contact_db else None) or {}

        msg_count = persist_messages(req.contact_id, messages, contact_profile)
        log_pipeline_event("pipeline_progress", run_id=run_id,
                           message=f"写入 {msg_count} 条消息到本地数据库")

        # Step 3: AI解析
        chat_content = format_dm_messages(req.contact_id, messages, date_desc)
        from main import step_parse
        profile = await _run_step(run_id, "parse_profile",
                                  lambda: step_parse(chat_content),
                                  f"{len(chat_content)} 字符",
                                  lambda r: f"提取 {sum(1 for v in r.model_dump().values() if v is not None)} 个字段")

        # 保存本地
        output_path = Path(__file__).parent.parent.parent / settings.DATA_DIR / f"profile_{req.contact_id}.json"
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(
            json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 保存画像到本地数据库
        persist_profile_to_db(req.contact_id, profile)

        # Step 4: 同步飞书（只在 parse_only=False 时执行）
        if not req.parse_only:
            from main import step_sync_feishu
            result = await asyncio.to_thread(step_sync_feishu, profile)
            eid = log_step("sync_feishu", run_id, input=f"name={profile.name}")
            update_run(run_id, steps={**_get_steps(run_id), "sync_feishu": "active"})
            if result:
                log_step_end(eid, output=f"action={result['action']}")
                update_run(run_id, steps={**_get_steps(run_id), "sync_feishu": "done"})
            else:
                log_step_end(eid, output="跳过（未配置飞书）")
                update_run(run_id, steps={**_get_steps(run_id), "sync_feishu": "skipped"})

        log_pipeline_event("pipeline_end", run_id=run_id, status="completed")
        update_run(run_id, status="completed", endTime=now())
        finish_run(run_id, "completed")

    except Exception as e:
        log_pipeline_event("pipeline_end", run_id=run_id, status="failed", error=str(e))
        update_run(run_id, status="failed", error=str(e), endTime=now())
        finish_run(run_id, "failed", str(e))


async def _execute_pipeline_all(run_id: str, req: PipelineRequest):
    log_pipeline_event("pipeline_start", run_id=run_id, contact_id="__all__")
    update_run(run_id, contact="__all__", contact_name="所有人",
               status="running", startTime=now(),
               steps={"decrypt_db": "active"}, error="", message="")

    try:
        # Step 1: 解密
        db_paths = await _run_step(run_id, "decrypt_db",
                                   lambda: ensure_decrypted(),
                                   "contact=__all__",
                                   lambda r: f"解密 {len(r)} 个数据库")

        # Step 2: 获取联系人并逐个处理
        from services.sync.extract import get_dm_contacts_with_messages, extract_dm_messages, format_dm_messages
        from services.sync.persist import persist_messages, persist_profile as persist_profile_to_db
        from main import step_parse, step_sync_feishu

        update_run(run_id, steps={"decrypt_db": "done", "extract_dm": "active"})
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
                msg = f"用户停止: 已处理 {processed}, 跳过 {skipped}, 失败 {failed}"
                log_pipeline_event("pipeline_end", run_id=run_id, status="completed", message=msg)
                finish_run(run_id, "completed", f"用户停止于第 {idx}/{total} 个")
                return

            contact_id = contact["wxid"]
            display_name = contact.get("alias") or contact.get("nickname") or contact_id
            date_desc = req.date_start and req.date_end and f"{req.date_start}~{req.date_end}" or req.date or "全部"

            log_pipeline_event("pipeline_progress", run_id=run_id,
                               message=f"[{idx}/{total}] {display_name} — 提取消息中...")
            update_run(run_id, message=f"[{idx}/{total}] {display_name} — 提取消息中...")

            try:
                messages = await asyncio.to_thread(
                    extract_dm_messages, db_paths, contact_id,
                    req.date, req.date_start, req.date_end,
                    limit=BATCH_LIMIT,
                )

                # 确保客户记录存在且带 nickname
                from services.db import upsert_customer
                upsert_customer(contact_id, nickname=display_name)
            except Exception:
                failed += 1
                continue

            if not messages:
                skipped += 1
                continue

            chat_content = format_dm_messages(display_name, messages, date_desc)

                # 写入本地数据库
            persist_messages(contact_id, messages, None)

            log_pipeline_event("pipeline_progress", run_id=run_id,
                               message=f"[{idx}/{total}] {display_name} — AI 解析中 ({len(messages)} 条)")
            update_run(run_id, message=f"[{idx}/{total}] {display_name} — AI 解析中 ({len(messages)} 条)",
                       steps={"decrypt_db": "done", "extract_dm": "done", "parse_profile": "active", "sync_feishu": ""})

            try:
                profile = await step_parse(chat_content)

                output_path = Path(__file__).parent.parent.parent / settings.DATA_DIR / f"profile_{contact_id}.json"
                output_path.parent.mkdir(exist_ok=True)
                output_path.write_text(
                    json.dumps(profile.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                    # 保存画像到本地数据库
                persist_profile_to_db(contact_id, profile)

                if not req.parse_only:
                    await asyncio.to_thread(step_sync_feishu, profile)

                processed += 1
                log_pipeline_event("pipeline_progress", run_id=run_id,
                                   message=f"[{idx}/{total}] {display_name} — 完成 (累计 {processed} 个)")
                update_run(run_id,
                           message=f"[{idx}/{total}] {display_name} — 完成 (累计 {processed} 个)",
                           steps={"decrypt_db": "done", "extract_dm": "done", "parse_profile": "done", "sync_feishu": "done"})
            except Exception:
                failed += 1

        summary = f"完成: {processed} 个解析成功, {skipped} 个无消息, {failed} 个失败"
        log_pipeline_event("pipeline_end", run_id=run_id, status="completed", message=summary)
        update_run(run_id, status="completed", message=summary, endTime=now())
        finish_run(run_id, "completed", summary)

    except asyncio.CancelledError:
        log_pipeline_event("pipeline_end", run_id=run_id, status="completed", message="用户手动停止")
        update_run(run_id, status="completed", message="用户手动停止", endTime=now())
        finish_run(run_id, "completed", "用户手动停止")
    except Exception as e:
        log_pipeline_event("pipeline_end", run_id=run_id, status="failed", error=str(e))
        update_run(run_id, status="failed", error=str(e), endTime=now())
        finish_run(run_id, "failed", str(e))


# ── Step runner helper ──

def _get_steps(run_id: str) -> dict:
    return get_run_steps(run_id)


async def _run_step(run_id: str, step_name: str, fn, input_desc: str, output_fn, post_update=None):
    """通用步骤执行器：记录开始/结束、更新状态、处理异常"""
    eid = log_step(step_name, run_id, input=input_desc)
    update_run(run_id, steps={**_get_steps(run_id), step_name: "active"})
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            result = await result
        log_step_end(eid, output=output_fn(result))
        update_run(run_id, steps={**_get_steps(run_id), step_name: "done"})
        if post_update:
            post_update(result)
        return result
    except Exception as e:
        log_step_end(eid, error=str(e))
        update_run(run_id, steps={**_get_steps(run_id), step_name: "failed"})
        raise


# ── Manual Feishu Sync ──


@router.post("/sync-feishu")
async def sync_feishu_all():
    """从本地 DB 读取所有客户画像，逐个同步到飞书。"""
    from services.db import get_all_customers
    from models import CustomerProfile
    from main import step_sync_feishu

    customers = get_all_customers()
    synced = 0
    failed = 0
    for c in customers:
        profile_json = c.get("profile_json")
        if not profile_json:
            continue
        try:
            profile = CustomerProfile.model_validate_json(profile_json)
            # 补充唯一标识字段：wxid 作为 wechat_id 用于飞书去重
            if not profile.wechat_id:
                profile.wechat_id = c.get("wxid") or c.get("wechat_id")
            if not profile.phone:
                profile.phone = c.get("phone")
            if not profile.wechat_name:
                profile.wechat_name = c.get("nickname") or c.get("alias")
            await asyncio.to_thread(step_sync_feishu, profile)
            synced += 1
        except Exception as e:
            failed += 1

    return {"synced": synced, "failed": failed, "total": len(customers)}
