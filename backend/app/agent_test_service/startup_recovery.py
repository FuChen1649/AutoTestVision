"""服务启动时回收未正常结束的 Agent / 批量任务。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.repository import agent_repository
from app.models.agent import (
    AgentBatchResult,
    AgentBatchRun,
    AgentRun,
    AgentRunStep,
    AgentRunStepAttempt,
)

logger = get_agent_logger()

STALE_ERROR = "服务重启或意外中断"
ACTIVE_STATUSES = ("pending", "running")


async def recover_stale_agent_tasks(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    recovered_batches = 0
    recovered_runs = 0

    stale_batches = (
        await db.execute(
            select(AgentBatchRun)
            .options(selectinload(AgentBatchRun.results))
            .where(AgentBatchRun.status.in_(ACTIVE_STATUSES))
        )
    ).scalars().all()

    for batch in stale_batches:
        case_ids = json.loads(batch.case_ids_json or "[]")
        existing_orders = {item.case_order for item in batch.results}
        completed = batch.completed_cases
        passed = batch.passed_cases
        failed = batch.failed_cases

        runs = (
            await db.execute(
                select(AgentRun)
                .options(selectinload(AgentRun.steps))
                .where(AgentRun.batch_id == batch.id)
            )
        ).scalars().all()

        for run in runs:
            if run.source_case_id not in case_ids:
                continue
            case_order = case_ids.index(run.source_case_id)
            if case_order in existing_orders:
                continue

            if run.status in ACTIVE_STATUSES:
                run.status = "failed"
                run.error = STALE_ERROR
                run.updated_at = now
                recovered_runs += 1

            await agent_repository.create_batch_result(db, batch, run, case_order)
            existing_orders.add(case_order)
            completed += 1
            if run.status == "completed":
                passed += 1
            else:
                failed += 1

        batch.status = "failed"
        batch.error = STALE_ERROR
        batch.completed_cases = completed
        batch.passed_cases = passed
        batch.failed_cases = failed
        batch.updated_at = now
        recovered_batches += 1

    run_update = await db.execute(
        update(AgentRun)
        .where(AgentRun.status.in_(ACTIVE_STATUSES))
        .values(status="failed", error=STALE_ERROR, updated_at=now)
    )
    recovered_runs += run_update.rowcount or 0

    await db.execute(
        update(AgentRunStep)
        .where(AgentRunStep.status.in_(ACTIVE_STATUSES))
        .values(status="failed", error=STALE_ERROR)
    )
    await db.execute(
        update(AgentRunStepAttempt)
        .where(AgentRunStepAttempt.status.in_(ACTIVE_STATUSES))
        .values(status="failed", error=STALE_ERROR)
    )
    await db.execute(
        update(AgentBatchResult)
        .where(AgentBatchResult.status.in_(ACTIVE_STATUSES))
        .values(status="failed", error=STALE_ERROR, updated_at=now)
    )
    await db.execute(
        update(AgentBatchRun)
        .where(AgentBatchRun.status.in_(ACTIVE_STATUSES))
        .values(status="failed", error=STALE_ERROR, updated_at=now)
    )

    await db.commit()

    if recovered_batches or recovered_runs:
        logger.info(
            "[startup_recovery] 已回收未完成任务 batches=%d runs=%d",
            recovered_batches,
            recovered_runs,
        )
