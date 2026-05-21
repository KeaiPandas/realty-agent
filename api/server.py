"""FastAPI 应用入口"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"

# 关闭 uvicorn access log（只保留 error 级别）
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from api.scheduler import scheduler_manager
    scheduler_manager.start()
    yield
    scheduler_manager.shutdown()


app = FastAPI(title="Realty Agent Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import workflow, scheduler_router, health, logs, bot_router, bot_events
app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(scheduler_router.router, prefix="/api/scheduler", tags=["scheduler"])
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(bot_router.router, prefix="/api/bot", tags=["bot"])
app.include_router(bot_events.router, prefix="/api/bot", tags=["bot-events"])

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")
