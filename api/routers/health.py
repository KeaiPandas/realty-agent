"""环境健康检测"""
from pathlib import Path

from fastapi import APIRouter

from config import settings

router = APIRouter()


def _check_wechat_process() -> dict:
    try:
        import psutil
        procs = [p for p in psutil.process_iter(["name"])
                 if p.info["name"] and ("WeChat" in p.info["name"] or "Weixin" in p.info["name"])]
        if procs:
            names = set(p.info["name"] for p in procs)
            return {"status": "ok", "message": f"微信进程运行中 ({', '.join(names)})"}
        return {"status": "error", "message": "未检测到微信进程，请先登录微信"}
    except Exception as e:
        return {"status": "error", "message": f"检测失败: {e}"}


def _check_wechat_db() -> dict:
    data_dir = settings.WECHAT_DATA_DIR
    if not data_dir:
        try:
            from adapters.wechat_path import detect_wechat_data_dir, persist_data_dir
            from adapters.db_layout import detect_wechat_version
            version = detect_wechat_version()
            detected = detect_wechat_data_dir(version)
            if detected:
                persist_data_dir(detected)
                data_dir = detected
        except Exception:
            pass
    if data_dir:
        data_path = Path(data_dir)
        # 4.x: db_storage/ 目录
        storage_dir = data_path / "db_storage"
        if storage_dir.exists():
            db_files = list(storage_dir.rglob("*.db"))
            if db_files:
                return {"status": "ok", "message": f"找到 {len(db_files)} 个数据库文件 (4.x)"}
        # 3.x: Msg/ 目录
        msg_dir = data_path / "Msg"
        if msg_dir.exists():
            db_files = list(msg_dir.glob("*.db"))
            if db_files:
                return {"status": "ok", "message": f"找到 {len(db_files)} 个数据库文件 (3.x)"}
        return {
            "status": "error",
            "message": (
                f"目录结构不匹配: {data_dir}。"
                "4.x 需要 db_storage/ 子目录，3.x 需要 Msg/ 子目录"
            ),
        }
    try:
        import io, sys
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            from adapters.db_layout import detect_wechat_version
            version = detect_wechat_version()
            return {"status": "error", "message": f"检测到微信 {version} 进程，但数据目录自动检测失败，请手动配置 WECHAT_DATA_DIR"}
        finally:
            sys.stderr = old_stderr
    except Exception as e:
        return {
            "status": "error",
            "message": (
                f"自动检测失败: {e}。"
                "请在 .env 中配置 WECHAT_DATA_DIR"
            ),
        }


def _check_feishu() -> dict:
    lark_path = Path(settings.LARK_CLI_PATH)
    if not lark_path.exists():
        return {
            "status": "error",
            "message": (
                f"lark-cli 未找到: {lark_path}。"
                "请安装: npm install -g @larksuite/cli，"
                "或在 config/sync.yaml 中配置 lark_cli_path"
            ),
        }
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
