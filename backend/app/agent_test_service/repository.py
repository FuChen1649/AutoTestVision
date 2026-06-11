import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.schemas import (
    ActionIntent,
    AgentLogItem,
    BatchListItem,
    BatchResultItem,
    BatchStateResponse,
    RunStateResponse,
    StepAttemptRecord,
    StepExecutionRecord,
    VerificationResult,
)
from app.agent_test_service.tools import parse_step_metadata
from app.models.agent import (
    AgentBatchResult,
    AgentBatchRun,
    AgentLog,
    AgentRun,
    AgentRunStep,
    AgentRunStepAttempt,
)
from app.models.case import Case


class AgentRepository:
    async def create_run(
        self,
        db: AsyncSession,
        case: Case,
        serial: str | None,
        max_retries: int,
        llm_provider: str | None = None,
        enable_verifier: bool = False,
        batch_id: int | None = None,
        auto_commit: bool = True,
    ) -> AgentRun:
        run = AgentRun(
            run_uuid=str(uuid.uuid4()),
            batch_id=batch_id,
            source_case_id=case.id,
            case_name=case.name,
            serial=serial,
            status="pending",
            current_step_index=0,
            total_steps=len(case.steps),
            retry_count=0,
            max_retries=max_retries,
            llm_provider=llm_provider,
            enable_verifier=enable_verifier,
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
        if auto_commit:
            await db.commit()
        else:
            await db.flush()
        await db.refresh(run, attribute_names=["steps", "logs", "attempts"])
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
        if "logs" not in sa_inspect(run).unloaded:
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

    def _step_action_context(self, step: AgentRunStep) -> tuple[str, ActionIntent | None, dict | None]:
        intent = None
        if step.intent_json:
            intent = ActionIntent.model_validate_json(step.intent_json)
        metadata = parse_step_metadata(step.metadata_json)
        return step.step_type, intent, metadata or None

    def _loaded_relationship(self, obj: object, name: str) -> list:
        state = sa_inspect(obj)
        if state is None or name in state.unloaded:
            return []
        return list(getattr(obj, name))

    def _attempts_to_records(self, run: AgentRun) -> list[StepAttemptRecord]:
        step_by_order = {item.step_order: item for item in self._loaded_relationship(run, "steps")}

        def enrich(item: AgentRunStepAttempt) -> StepAttemptRecord:
            step = step_by_order.get(item.step_order)
            step_type, intent, metadata = (None, None, None)
            if step is not None:
                step_type, intent, metadata = self._step_action_context(step)
            return StepAttemptRecord(
                step_order=item.step_order,
                attempt_index=item.attempt_index,
                before_image=item.before_image,
                before_image_annotated=item.before_image_annotated,
                after_image=item.after_image,
                status=item.status,
                error=item.error,
                step_type=step_type,
                intent=intent if item.status == "success" else None,
                metadata=metadata if item.status == "success" else None,
            )

        records = [
            enrich(item)
            for item in sorted(
                self._loaded_relationship(run, "attempts"),
                key=lambda row: (row.step_order, row.attempt_index),
            )
        ]
        if records:
            return records

        fallback: list[StepAttemptRecord] = []
        for step in sorted(self._loaded_relationship(run, "steps"), key=lambda item: item.step_order):
            if not (step.before_image or step.before_image_annotated or step.after_image):
                continue
            step_type, intent, metadata = self._step_action_context(step)
            is_success = step.status == "success"
            fallback.append(
                StepAttemptRecord(
                    step_order=step.step_order,
                    attempt_index=0,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    status=step.status if step.status in {"success", "failed"} else "running",
                    error=step.error,
                    step_type=step_type,
                    intent=intent if is_success else None,
                    metadata=metadata if is_success else None,
                )
            )
        return fallback

    def to_response(self, run: AgentRun) -> RunStateResponse:
        steps: list[StepExecutionRecord] = []
        for step in sorted(self._loaded_relationship(run, "steps"), key=lambda item: item.step_order):
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
            enable_verifier=bool(getattr(run, "enable_verifier", False)),
            steps=steps,
            attempts=self._attempts_to_records(run),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    async def create_batch(
        self,
        db: AsyncSession,
        serial: str | None,
        total_cases: int,
        case_ids: list[int],
        llm_provider: str | None = None,
        enable_verifier: bool = False,
    ) -> AgentBatchRun:
        batch = AgentBatchRun(
            batch_uuid=str(uuid.uuid4()),
            status="pending",
            serial=serial,
            llm_provider=llm_provider,
            enable_verifier=enable_verifier,
            total_cases=total_cases,
            case_ids_json=json.dumps(case_ids, ensure_ascii=False),
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch, attribute_names=["results"])
        return batch

    async def get_batch_by_uuid(self, db: AsyncSession, batch_uuid: str) -> AgentBatchRun | None:
        result = await db.execute(
            select(AgentBatchRun)
            .options(selectinload(AgentBatchRun.results))
            .where(AgentBatchRun.batch_uuid == batch_uuid)
        )
        return result.scalar_one_or_none()

    async def list_batches(self, db: AsyncSession, limit: int = 50) -> list[AgentBatchRun]:
        result = await db.execute(
            select(AgentBatchRun).order_by(AgentBatchRun.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def update_batch_fields(self, db: AsyncSession, batch: AgentBatchRun, **fields) -> AgentBatchRun:
        for key, value in fields.items():
            setattr(batch, key, value)
        batch.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return batch

    async def create_batch_result(
        self,
        db: AsyncSession,
        batch: AgentBatchRun,
        run: AgentRun,
        case_order: int,
    ) -> AgentBatchResult:
        for item in self._loaded_relationship(batch, "results"):
            if item.case_order == case_order:
                return item

        passed_steps = sum(
            1 for step in self._loaded_relationship(run, "steps") if step.status == "success"
        )
        result = AgentBatchResult(
            batch_id=batch.id,
            run_id=run.id,
            run_uuid=run.run_uuid,
            case_id=run.source_case_id,
            case_name=run.case_name,
            case_order=case_order,
            status=run.status,
            total_steps=run.total_steps,
            passed_steps=passed_steps,
            error=run.error,
        )
        db.add(result)
        if "results" not in sa_inspect(batch).unloaded:
            batch.results.append(result)
        await db.flush()
        return result

    def batch_result_to_item(self, result: AgentBatchResult) -> BatchResultItem:
        return BatchResultItem(
            result_id=result.id,
            run_id=result.run_uuid,
            case_id=result.case_id,
            case_name=result.case_name,
            case_order=result.case_order,
            status=result.status,
            total_steps=result.total_steps,
            passed_steps=result.passed_steps,
            error=result.error,
            created_at=result.created_at,
            updated_at=result.updated_at,
        )

    def to_batch_response(self, batch: AgentBatchRun) -> BatchStateResponse:
        results = [
            self.batch_result_to_item(item)
            for item in sorted(self._loaded_relationship(batch, "results"), key=lambda row: row.case_order)
        ]
        return BatchStateResponse(
            batch_id=batch.batch_uuid,
            status=batch.status,  # type: ignore[arg-type]
            serial=batch.serial,
            llm_provider=batch.llm_provider,
            enable_verifier=bool(batch.enable_verifier),
            total_cases=batch.total_cases,
            completed_cases=batch.completed_cases,
            passed_cases=batch.passed_cases,
            failed_cases=batch.failed_cases,
            error=batch.error,
            results=results,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def to_batch_list_item(self, batch: AgentBatchRun) -> BatchListItem:
        return BatchListItem(
            batch_id=batch.batch_uuid,
            status=batch.status,  # type: ignore[arg-type]
            total_cases=batch.total_cases,
            completed_cases=batch.completed_cases,
            passed_cases=batch.passed_cases,
            failed_cases=batch.failed_cases,
            llm_provider=batch.llm_provider,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
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
