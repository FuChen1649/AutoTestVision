import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_code_service.schemas import (
    AgentLogItem,
    CodeRunStateResponse,
    CodeStepExecutionRecord,
    GeneratedStepCode,
)
from app.agent_test_service.schemas import VerificationResult
from app.agent_test_service.tools import parse_step_metadata
from app.models.agent_code import (
    AgentCodeBatchResult,
    AgentCodeBatchRun,
    AgentCodeLog,
    AgentCodeRun,
    AgentCodeRunStep,
)
from app.models.case import Case


class AgentCodeRepository:
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
    ) -> AgentCodeRun:
        run = AgentCodeRun(
            run_uuid=str(uuid.uuid4()),
            batch_id=batch_id,
            source_case_id=case.id,
            case_name=case.name,
            script_content=case.script_content or "",
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
                AgentCodeRunStep(
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
                    generated_code_json=step.code_script_json,
                )
            )
        db.add(run)
        if auto_commit:
            await db.commit()
        else:
            await db.flush()
        await db.refresh(run, attribute_names=["steps", "logs", "attempts"])
        return run

    async def get_run_by_uuid(self, db: AsyncSession, run_uuid: str) -> AgentCodeRun | None:
        result = await db.execute(
            select(AgentCodeRun)
            .options(
                selectinload(AgentCodeRun.steps),
                selectinload(AgentCodeRun.logs),
                selectinload(AgentCodeRun.attempts),
            )
            .where(AgentCodeRun.run_uuid == run_uuid)
        )
        return result.scalar_one_or_none()

    async def add_log(
        self,
        db: AsyncSession,
        run: AgentCodeRun,
        agent_type: str,
        message: str,
        step_order: int | None = None,
        detail: dict | None = None,
    ) -> AgentCodeLog:
        log = AgentCodeLog(
            run_id=run.id,
            step_order=step_order,
            agent_type=agent_type,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(log)
        await db.flush()
        return log

    async def update_run_fields(self, db: AsyncSession, run: AgentCodeRun, **fields) -> AgentCodeRun:
        for key, value in fields.items():
            setattr(run, key, value)
        run.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return run

    async def commit(self, db: AsyncSession) -> None:
        await db.commit()

    def logs_to_items(self, run: AgentCodeRun, agent_type: str | None = None) -> list[AgentLogItem]:
        logs = sorted(run.logs, key=lambda item: item.created_at)
        if agent_type:
            logs = [item for item in logs if item.agent_type == agent_type]
        return [
            AgentLogItem(
                id=item.id,
                step_order=item.step_order,
                agent_type=item.agent_type,
                message=item.message,
                created_at=item.created_at,
            )
            for item in logs
        ]

    def to_response(self, run: AgentCodeRun) -> CodeRunStateResponse:
        steps: list[CodeStepExecutionRecord] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            generated = None
            verification = None
            if step.generated_code_json:
                generated = GeneratedStepCode.model_validate_json(step.generated_code_json)
                if step.template_path:
                    generated.template_path = step.template_path
                if step.execution_output:
                    generated.execution_output = step.execution_output
            if step.verification_json:
                verification = VerificationResult.model_validate_json(step.verification_json)
            xml_preview = (step.ui_xml or "")[:500] if step.ui_xml else None
            steps.append(
                CodeStepExecutionRecord(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    status=step.status,  # type: ignore[arg-type]
                    generated_code=generated,
                    verification=verification,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    ui_xml_preview=xml_preview,
                    reference_image=step.reference_image,
                    reference_x=step.reference_x,
                    reference_y=step.reference_y,
                    reference_width=step.reference_width,
                    reference_height=step.reference_height,
                    error=step.error,
                    metadata=parse_step_metadata(step.metadata_json),
                )
            )
        return CodeRunStateResponse(
            run_id=run.run_uuid,
            case_id=run.source_case_id,
            case_name=run.case_name,
            script_content=run.script_content or "",
            serial=run.serial,
            status=run.status,  # type: ignore[arg-type]
            current_step_index=run.current_step_index,
            total_steps=run.total_steps,
            retry_count=run.retry_count,
            max_retries=run.max_retries,
            error=run.error,
            llm_provider=run.llm_provider,
            enable_verifier=run.enable_verifier,
            steps=steps,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    async def sync_steps_from_state(
        self, db: AsyncSession, run: AgentCodeRun, records: list[CodeStepExecutionRecord]
    ) -> None:
        step_map = {item.step_order: item for item in run.steps}
        for record in records:
            step = step_map.get(record.step_order)
            if not step:
                continue
            step.status = record.status
            step.description = record.description
            step.before_image = record.before_image
            step.before_image_annotated = record.before_image_annotated
            step.after_image = record.after_image
            step.error = record.error
            if record.generated_code:
                step.generated_code_json = json.dumps(
                    record.generated_code.model_dump(), ensure_ascii=False
                )
                step.template_path = record.generated_code.template_path
                step.execution_output = record.generated_code.execution_output
            if record.verification:
                step.verification_json = json.dumps(
                    record.verification.model_dump(), ensure_ascii=False
                )
            if record.ui_xml_preview and not step.ui_xml:
                pass
        await db.flush()


agent_code_repository = AgentCodeRepository()
