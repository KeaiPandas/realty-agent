"""环境健康检测"""
from pathlib import Path

from fastapi import APIRouter

from config import settings

router = APIRouter()


def _check_wechat_process() -> dict:
    try:
        import psutil
        procs = [p for p in psutil.process_iter(["name"])
                 if p.info["name"] and "WeChat" in p.info["name"]]
        if procs:
            return {"status": "ok", "message": "微信进程运行中"}
        return {"status": "error", "message": "未检测到微信进程，请先登录微信"}
    except Exception as e:
        return {"status": "error", "message": f"检测失败: {e}"}


def _check_wechat_db() -> dict:
    if settings.WECHAT_DATA_DIR:
        msg_dir = Path(settings.WECHAT_DATA_DIR) / "Msg"
        if msg_dir.exists():
            db_files = list(msg_dir.glob("*.db"))
            if db_files:
                return {"status": "ok", "message": f"找到 {len(db_files)} 个数据库文件"}
            return {"status": "error", "message": f"Msg 目录下无 .db 文件: {msg_dir}"}
        return {"status": "error", "message": f"目录不存在: {msg_dir}"}
    try:
        import io, sys
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            from adapters.decrypt import get_wx_info
            info = get_wx_info()
        finally:
            sys.stderr = old_stderr
        if info and isinstance(info, list) and info[0].get("wx_dir"):
            return {"status": "ok", "message": "已通过 pywxdump 自动检测到微信数据"}
        return {"status": "error", "message": "无法自动检测微信数据目录，请在 config/wechat.yaml 配置 data_dir"}
    except Exception as e:
        return {"status": "error", "message": f"自动检测失败: {e}"}


def _check_feishu() -> dict:
    lark_path = Path(settings.LARK_CLI_PATH)
    if not lark_path.exists():
        return {"status": "error", "message": f"lark-cli 未找到: {lark_path}"}
    has_token = bool(settings.FEISHU_BASE_TOKEN)
    has_table = bool(settings.FEISHU_TABLE_ID)
    if has_token and has_table:
        return {"status": "ok", "message": "lark-cli 就绪，飞书令牌已配置"}
    missing = []
    if not has_token:
        missing.append("FEISHU_BASE_TOKEN")
    if not has_table:
        missing.append("FEISHU_TABLE_ID")
    return {"status": "error", "message": f"lark-cli 就绪，但缺少: {', '.join(missing)}"}


async def _check_llm() -> dict:
    if not settings.LLM_API_KEY:
        return {"status": "error", "message": "LLM_API_KEY 未配置"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.LLM_BASE_URL}/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            )
            if resp.status_code == 200:
                return {"status": "ok", "message": f"API 连通，模型 {settings.LLM_MODEL}"}
            return {"status": "error", "message": f"API 返回状态码 {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {e}"}


@router.get("")
async def health_check():
    checks = {
        "wechat_process": _check_wechat_process(),
        "wechat_db": _check_wechat_db(),
        "feishu": _check_feishu(),
        "llm": await _check_llm(),
    }
    statuses = [v["status"] for v in checks.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "degraded"
    else:
        overall = "down"
    return {"checks": checks, "overall": overall}
