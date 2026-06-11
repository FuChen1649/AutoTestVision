"""Agent 服务独立启动入口。

在 backend 目录下执行：
    .venv\\Scripts\\python.exe -m app.agent_test_service.run_agent_service
    .venv\\Scripts\\python.exe app/agent_test_service/run_agent_service.py --port 8100

启动后会：
  1. 创建 backend/logs/agent_service_<时间戳>.log
  2. 自检数据库、路由、LLM/ADB 配置
  3. 仅暴露 /api/agent-test/* 接口（默认端口 8100，主后端为 8099）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent_test_service.agent_logger import get_log_file, init_agent_logger

logger = init_agent_logger()

from app.api import agent_test  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, async_session, engine  # noqa: E402
from app.models import agent as _agent_models  # noqa: E402, F401
from app.agent_test_service.startup_recovery import recover_stale_agent_tasks  # noqa: E402
from app.services.adb import adb_service  # noqa: E402


async def run_startup_checks(app: FastAPI) -> None:
    logger.info("========== Agent 服务启动自检 ==========")

    routes = sorted(
        route.path
        for route in app.routes
        if hasattr(route, "path") and route.path.startswith("/api/agent-test")
    )
    logger.info("已注册 Agent 路由 (%d): %s", len(routes), ", ".join(routes) or "(无)")

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("数据库连接: 正常 (%s)", settings.database_url.split("@")[-1])
    except Exception as exc:
        logger.error("数据库连接: 失败 - %s", exc)

    if settings.agent_llm_api_key:
        logger.info(
            "LLM 配置: 已启用 model=%s base_url=%s",
            settings.agent_llm_model,
            settings.agent_llm_base_url or "(默认)",
        )
    else:
        logger.warning("LLM 配置: 未设置 AGENT_LLM_API_KEY，将使用启发式分析/验证")

    try:
        devices = adb_service.list_devices()
        if devices:
            logger.info("ADB 设备 (%d): %s", len(devices), ", ".join(d.serial for d in devices))
        else:
            logger.warning("ADB 设备: 未检测到已连接设备")
    except Exception as exc:
        logger.warning("ADB 检测失败: %s", exc)

    log_file = get_log_file()
    if log_file:
        logger.info("运行日志: %s", log_file)
    logger.info("========== 自检完成，等待请求 ==========")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        await recover_stale_agent_tasks(db)
    await run_startup_checks(app)
    yield
    await engine.dispose()
    logger.info("Agent 服务已关闭")


def create_agent_app() -> FastAPI:
    app = FastAPI(
        title="AutoTestVision Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agent_test.router, prefix="/api")

    @app.get("/api/agent-test/health")
    async def agent_health() -> dict[str, str]:
        return {"status": "ok", "service": "agent-test"}

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立启动 AutoTestVision Agent 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8100, help="监听端口，默认 8100")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("启动 Agent 独立服务 host=%s port=%d", args.host, args.port)
    print()
    print("=" * 50)
    print("  AutoTestVision Agent 独立服务")
    print(f"  地址: http://localhost:{args.port}")
    print(f"  健康检查: http://localhost:{args.port}/api/agent-test/health")
    print(f"  Case 列表: http://localhost:{args.port}/api/agent-test/cases?limit=10")
    log_file = get_log_file()
    if log_file:
        print(f"  日志文件: {log_file}")
    print("=" * 50)
    print()

    uvicorn.run(
        create_agent_app(),
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
