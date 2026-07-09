from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import agent_monkey, agent_test, agent_test_code, batch, case_live, cases, device, flywheel, logs, reports, result_verify, script_generation, tasks
from app.config import settings
from app.database import Base, async_session, engine
from app.models import agent as _agent_models  # noqa: F401
from app.models import agent_code as _agent_code_models  # noqa: F401
from app.models import case_assertion as _case_assertion_models  # noqa: F401
from app.models import flywheel as _flywheel_models  # noqa: F401
from app.models import monkey as _monkey_models  # noqa: F401
from app.models import platform_log as _platform_log_models  # noqa: F401
from app.models import task as _task_models  # noqa: F401
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
            "ALTER TABLE agent_run_steps ADD COLUMN IF NOT EXISTS purpose_review_json TEXT",
            "ALTER TABLE agent_code_run_steps ADD COLUMN IF NOT EXISTS purpose_review_json TEXT",
            "ALTER TABLE monkey_screen_actions ADD COLUMN IF NOT EXISTS element_node_uuid TEXT",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS position_script_json TEXT",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS code_script_json TEXT",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS script_generated_at TIMESTAMPTZ",
            "ALTER TABLE case_steps ADD COLUMN IF NOT EXISTS script_status TEXT",
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
app.include_router(case_live.router, prefix="/api")
app.include_router(device.router, prefix="/api")
app.include_router(agent_test.router, prefix="/api")
app.include_router(agent_test_code.router, prefix="/api")
app.include_router(agent_monkey.router, prefix="/api")
app.include_router(result_verify.router, prefix="/api")
app.include_router(flywheel.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(script_generation.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(batch.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
