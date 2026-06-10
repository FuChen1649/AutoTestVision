import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.schemas import (
    ActionIntent,
    AgentLogItem,
    RunStateResponse,
    StepAttemptRecord,
    StepExecutionRecord,
    VerificationResult,
)
from app.agent_test_service.tools import parse_step_metadata
from app.models.agent import AgentLog, AgentRun, AgentRunStep, AgentRunStepAttempt
from app.models.case import Case


class AgentRepository:
    async def create_run(
        self,
        db: AsyncSession,
        case: Case,
        serial: str | None,
        max_retries: int,
        llm_provider: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            run_uuid=str(uuid.uuid4()),
            source_case_id=case.id,
            case_name=case.name,
            serial=serial,
            status="pending",
            current_step_index=0,
            total_steps=len(case.steps),
            retry_count=0,
            max_retries=max_retries,
            llm_provider=llm_provider,
        )
        for step in sorted(case.steps, key=lambda item: item.step_order):
            run.steps.append(
                AgentRunStep(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    status="pending",
                    reference_image=step.screen_image,
                    reference_x=step.selection_x,
                    reference_y=step.selection_y,
                    reference_width=step.selection_width,
                    reference_height=step.selection_height,
                    metadata_json=step.metadata_json,
                )
            )
        db.add(run)
        await db.commit()
        await db.refresh(run, attribute_names=["steps", "logs"])
        return run

    async def get_run_by_uuid(self, db: AsyncSession, run_uuid: str) -> AgentRun | None:
        result = await db.execute(
            select(AgentRun)
            .options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.logs),
                selectinload(AgentRun.attempts),
            )
            .where(AgentRun.run_uuid == run_uuid)
        )
        return result.scalar_one_or_none()

    async def add_log(
        self,
        db: AsyncSession,
        run: AgentRun,
        agent_type: str,
        message: str,
        step_order: int | None = None,
        detail: dict | None = None,
    ) -> AgentLog:
        log = AgentLog(
            run_id=run.id,
            step_order=step_order,
            agent_type=agent_type,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(log)
        run.logs.append(log)
        await db.flush()
        return log

    async def update_run_fields(self, db: AsyncSession, run: AgentRun, **fields) -> AgentRun:
        for key, value in fields.items():
            setattr(run, key, value)
        run.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return run

    async def update_step(
        self,
        db: AsyncSession,
        run: AgentRun,
        step_order: int,
        **fields,
    ) -> AgentRunStep:
        step = next(item for item in run.steps if item.step_order == step_order)
        for key, value in fields.items():
            if key == "intent" and isinstance(value, ActionIntent):
                step.intent_json = json.dumps(value.model_dump(), ensure_ascii=False)
            elif key == "verification" and isinstance(value, VerificationResult):
                step.verification_json = json.dumps(value.model_dump(), ensure_ascii=False)
            else:
                setattr(step, key, value)
        await db.flush()
        return step

    async def commit(self, db: AsyncSession) -> None:
        await db.commit()

    async def create_attempt(
        self,
        db: AsyncSession,
        run: AgentRun,
        step_order: int,
        before_image: str | None,
    ) -> AgentRunStepAttempt:
        existing = [item for item in run.attempts if item.step_order == step_order]
        attempt_index = len(existing)
        attempt = AgentRunStepAttempt(
            run_id=run.id,
            step_order=step_order,
            attempt_index=attempt_index,
            before_image=before_image,
            status="running",
        )
        db.add(attempt)
        run.attempts.append(attempt)
        await db.flush()
        return attempt

    async def update_latest_attempt(
        self,
        db: AsyncSession,
        run: AgentRun,
        step_order: int,
        **fields,
    ) -> AgentRunStepAttempt | None:
        attempts = sorted(
            [item for item in run.attempts if item.step_order == step_order],
            key=lambda item: item.attempt_index,
        )
        if not attempts:
            return None
        attempt = attempts[-1]
        for key, value in fields.items():
            setattr(attempt, key, value)
        await db.flush()
        return attempt

    def _attempts_to_records(self, run: AgentRun) -> list[StepAttemptRecord]:
        records = [
            StepAttemptRecord(
                step_order=item.step_order,
                attempt_index=item.attempt_index,
                before_image=item.before_image,
                before_image_annotated=item.before_image_annotated,
                after_image=item.after_image,
                status=item.status,
                error=item.error,
            )
            for item in sorted(run.attempts, key=lambda row: (row.step_order, row.attempt_index))
        ]
        if records:
            return records

        fallback: list[StepAttemptRecord] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            if not (step.before_image or step.before_image_annotated or step.after_image):
                continue
            fallback.append(
                StepAttemptRecord(
                    step_order=step.step_order,
                    attempt_index=0,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    status=step.status if step.status in {"success", "failed"} else "running",
                    error=step.error,
                )
            )
        return fallback

    def to_response(self, run: AgentRun) -> RunStateResponse:
        steps: list[StepExecutionRecord] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            intent = None
            verification = None
            if step.intent_json:
                intent = ActionIntent.model_validate_json(step.intent_json)
            if step.verification_json:
                verification = VerificationResult.model_validate_json(step.verification_json)
            steps.append(
                StepExecutionRecord(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    status=step.status,
                    intent=intent,
                    verification=verification,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    reference_image=step.reference_image,
                    reference_x=step.reference_x,
                    reference_y=step.reference_y,
                    reference_width=step.reference_width,
                    reference_height=step.reference_height,
                    error=step.error,
                    metadata=parse_step_metadata(step.metadata_json),
                )
            )

        return RunStateResponse(
            run_id=run.run_uuid,
            case_id=run.source_case_id,
            case_name=run.case_name,
            serial=run.serial,
            status=run.status,
            current_step_index=run.current_step_index,
            total_steps=run.total_steps,
            retry_count=run.retry_count,
            max_retries=run.max_retries,
            error=run.error,
            llm_provider=run.llm_provider,
            steps=steps,
            attempts=self._attempts_to_records(run),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    def logs_to_items(self, run: AgentRun, agent_type: str | None = None) -> list[AgentLogItem]:
        items = sorted(run.logs, key=lambda item: item.created_at)
        if agent_type:
            items = [item for item in items if item.agent_type == agent_type]
        result: list[AgentLogItem] = []
        for item in items:
            detail = None
            if item.detail_json:
                detail = json.loads(item.detail_json)
            result.append(
                AgentLogItem(
                    id=item.id,
                    step_order=item.step_order,
                    agent_type=item.agent_type,
                    message=item.message,
                    detail=detail,
                    created_at=item.created_at,
                )
            )
        return result


agent_repository = AgentRepository()
