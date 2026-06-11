from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import agent_test, cases, device
from app.config import settings
from app.database import Base, async_session, engine
from app.models import agent as _agent_models  # noqa: F401
from app.agent_test_service.startup_recovery import recover_stale_agent_tasks


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS step_type TEXT DEFAULT 'natural'")
        )
        for ddl in (
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS screen_image TEXT",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS screen_width INTEGER",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS screen_height INTEGER",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS selection_x INTEGER",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS selection_y INTEGER",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS selection_width INTEGER",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS selection_height INTEGER",
            "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS llm_provider TEXT",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS metadata_json TEXT",
            "ALTER TABLE agent_run_steps ADD COLUMN IF NOT EXISTS metadata_json TEXT",
            "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS enable_verifier BOOLEAN DEFAULT FALSE",
            "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS batch_id INTEGER",
            "ALTER TABLE agent_batch_runs ADD COLUMN IF NOT EXISTS case_ids_json TEXT",
        ):
            await conn.execute(text(ddl))
    async with async_session() as db:
        await recover_stale_agent_tasks(db)
    yield
    await engine.dispose()


app = FastAPI(title="AutoTestVision API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases.router, prefix="/api")
app.include_router(device.router, prefix="/api")
app.include_router(agent_test.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
