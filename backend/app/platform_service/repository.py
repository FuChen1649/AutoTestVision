import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import AgentRun
from app.models.agent_code import AgentCodeRun
from app.models.case import Case
from app.models.task import PlatformTask


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRepository:
    async def create(
        self,
        db: AsyncSession,
        *,
        task_type: str,
        exec_mode: str | None = None,
        source_case_id: int | None = None,
        case_name: str | None = None,
        ref_uuid: str | None = None,
        parent_task_uuid: str | None = None,
        serial: str | None = None,
        status: str = "pending",
        progress: dict | None = None,
    ) -> PlatformTask:
        task = PlatformTask(
            task_uuid=str(uuid.uuid4()),
            task_type=task_type,
            exec_mode=exec_mode,
            source_case_id=source_case_id,
            case_name=case_name,
            ref_uuid=ref_uuid,
            parent_task_uuid=parent_task_uuid,
            serial=serial,
            status=status,
            progress_json=json.dumps(progress or {}, ensure_ascii=False),
        )
        db.add(task)
        await db.flush()
        return task

    async def get_by_uuid(self, db: AsyncSession, task_uuid: str) -> PlatformTask | None:
        result = await db.execute(select(PlatformTask).where(PlatformTask.task_uuid == task_uuid))
        return result.scalar_one_or_none()

    async def update_status(
        self,
        db: AsyncSession,
        task: PlatformTask,
        *,
        status: str | None = None,
        progress: dict | None = None,
        error: str | None = None,
        ref_uuid: str | None = None,
    ) -> PlatformTask:
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress_json = json.dumps(progress, ensure_ascii=False)
        if error is not None:
            task.error = error
        if ref_uuid is not None:
            task.ref_uuid = ref_uuid
        task.updated_at = utc_now()
        await db.flush()
        return task

    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        task_type: str | None = None,
        status: str | None = None,
        case_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PlatformTask], int]:
        query = select(PlatformTask)
        count_query = select(func.count()).select_from(PlatformTask)

        if task_type:
            query = query.where(PlatformTask.task_type == task_type)
            count_query = count_query.where(PlatformTask.task_type == task_type)
        if status:
            query = query.where(PlatformTask.status == status)
            count_query = count_query.where(PlatformTask.status == status)
        if case_id is not None:
            query = query.where(PlatformTask.source_case_id == case_id)
            count_query = count_query.where(PlatformTask.source_case_id == case_id)

        total = int((await db.execute(count_query)).scalar_one())
        result = await db.execute(
            query.order_by(PlatformTask.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total


class CaseQueryRepository:
    async def list_cases_paginated(
        self,
        db: AsyncSession,
        *,
        q: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Case], int]:
        query = select(Case).options(selectinload(Case.steps))
        count_query = select(func.count()).select_from(Case)

        if q:
            pattern = f"%{q.strip()}%"
            query = query.where(or_(Case.name.ilike(pattern), Case.script_content.ilike(pattern)))
            count_query = count_query.where(or_(Case.name.ilike(pattern), Case.script_content.ilike(pattern)))

        total = int((await db.execute(count_query)).scalar_one())
        offset = max(page - 1, 0) * size
        result = await db.execute(query.order_by(Case.updated_at.desc()).limit(size).offset(offset))
        return list(result.scalars().all()), total

    async def last_run_status(self, db: AsyncSession, case_id: int) -> str | None:
        pos = await db.execute(
            select(AgentRun.status)
            .where(AgentRun.source_case_id == case_id)
            .order_by(AgentRun.updated_at.desc())
            .limit(1)
        )
        pos_status = pos.scalar_one_or_none()
        code = await db.execute(
            select(AgentCodeRun.status)
            .where(AgentCodeRun.source_case_id == case_id)
            .order_by(AgentCodeRun.updated_at.desc())
            .limit(1)
        )
        code_status = code.scalar_one_or_none()
        if pos_status and code_status:
            if pos_status == "failed" or code_status == "failed":
                return "failed"
            if pos_status == "running" or code_status == "running":
                return "running"
            if pos_status == "completed" and code_status == "completed":
                return "completed"
            return pos_status
        return pos_status or code_status

    def aggregate_script_status(self, case: Case) -> str | None:
        statuses = [s.script_status for s in case.steps if s.script_status]
        if not statuses:
            return None
        if any(s == "failed" for s in statuses):
            return "failed"
        if any(s == "generating" for s in statuses):
            return "generating"
        if all(s == "ready" for s in statuses if s):
            natural_steps = [s for s in case.steps if s.step_type == "natural"]
            if natural_steps and all(s.script_status == "ready" for s in natural_steps):
                return "ready"
        return statuses[0]


task_repository = TaskRepository()
case_query_repository = CaseQueryRepository()
