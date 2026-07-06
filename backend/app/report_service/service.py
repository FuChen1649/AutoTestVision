import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import AgentBatchRun, AgentRun
from app.models.agent_code import AgentCodeBatchRun, AgentCodeRun
from app.report_service.schemas import ReportDetailResponse, ReportListResponse, ReportSummaryItem


class ReportService:
    async def list_reports(
        self,
        db: AsyncSession,
        *,
        exec_mode: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReportListResponse:
        items: list[ReportSummaryItem] = []

        if exec_mode in (None, "position"):
            pos_result = await db.execute(
                select(AgentBatchRun).order_by(AgentBatchRun.created_at.desc()).limit(limit)
            )
            for batch in pos_result.scalars().all():
                items.append(
                    ReportSummaryItem(
                        report_id=batch.batch_uuid,
                        report_type="batch",
                        exec_mode="position",
                        status=batch.status,
                        total_cases=batch.total_cases,
                        passed_cases=batch.passed_cases,
                        failed_cases=batch.failed_cases,
                        completed_cases=batch.completed_cases,
                        serial=batch.serial,
                        created_at=batch.created_at,
                        updated_at=batch.updated_at,
                    )
                )

        if exec_mode in (None, "code"):
            code_result = await db.execute(
                select(AgentCodeBatchRun).order_by(AgentCodeBatchRun.created_at.desc()).limit(limit)
            )
            for batch in code_result.scalars().all():
                items.append(
                    ReportSummaryItem(
                        report_id=batch.batch_uuid,
                        report_type="batch",
                        exec_mode="code",
                        status=batch.status,
                        total_cases=batch.total_cases,
                        passed_cases=batch.passed_cases,
                        failed_cases=batch.failed_cases,
                        completed_cases=batch.completed_cases,
                        serial=batch.serial,
                        created_at=batch.created_at,
                        updated_at=batch.updated_at,
                    )
                )

        items.sort(key=lambda x: x.created_at, reverse=True)
        page = items[offset : offset + limit]
        return ReportListResponse(items=page, total=len(items))

    async def get_report(self, db: AsyncSession, report_id: str, exec_mode: str = "position") -> ReportDetailResponse | None:
        if exec_mode == "code":
            result = await db.execute(
                select(AgentCodeBatchRun)
                .options(selectinload(AgentCodeBatchRun.results))
                .where(AgentCodeBatchRun.batch_uuid == report_id)
            )
            batch = result.scalar_one_or_none()
            if not batch:
                return None
            case_results = []
            for item in batch.results:
                case_results.append(
                    {
                        "case_id": item.case_id,
                        "case_name": item.case_name,
                        "status": item.status,
                        "run_uuid": item.run_uuid,
                        "total_steps": item.total_steps,
                        "passed_steps": item.passed_steps,
                        "error": item.error,
                    }
                )
            return ReportDetailResponse(
                report_id=batch.batch_uuid,
                report_type="batch",
                exec_mode="code",
                status=batch.status,
                total_cases=batch.total_cases,
                passed_cases=batch.passed_cases,
                failed_cases=batch.failed_cases,
                completed_cases=batch.completed_cases,
                case_results=case_results,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
            )

        result = await db.execute(
            select(AgentBatchRun)
            .options(selectinload(AgentBatchRun.results))
            .where(AgentBatchRun.batch_uuid == report_id)
        )
        batch = result.scalar_one_or_none()
        if not batch:
            return None
        case_results = []
        for item in batch.results:
            case_results.append(
                {
                    "case_id": item.case_id,
                    "case_name": item.case_name,
                    "status": item.status,
                    "run_uuid": item.run_uuid,
                    "total_steps": item.total_steps,
                    "passed_steps": item.passed_steps,
                    "error": item.error,
                }
            )
        return ReportDetailResponse(
            report_id=batch.batch_uuid,
            report_type="batch",
            exec_mode="position",
            status=batch.status,
            total_cases=batch.total_cases,
            passed_cases=batch.passed_cases,
            failed_cases=batch.failed_cases,
            completed_cases=batch.completed_cases,
            case_results=case_results,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    async def get_run_report(self, db: AsyncSession, run_uuid: str, exec_mode: str = "position") -> dict | None:
        if exec_mode == "code":
            result = await db.execute(
                select(AgentCodeRun)
                .options(selectinload(AgentCodeRun.steps))
                .where(AgentCodeRun.run_uuid == run_uuid)
            )
            run = result.scalar_one_or_none()
            if not run:
                return None
            steps = []
            for step in run.steps:
                code_line = None
                if step.generated_code_json:
                    try:
                        code_line = json.loads(step.generated_code_json).get("code_line")
                    except json.JSONDecodeError:
                        pass
                steps.append(
                    {
                        "step_order": step.step_order,
                        "description": step.description,
                        "status": step.status,
                        "code_line": code_line,
                    }
                )
            return {
                "run_uuid": run.run_uuid,
                "exec_mode": "code",
                "case_id": run.source_case_id,
                "case_name": run.case_name,
                "status": run.status,
                "steps": steps,
            }

        result = await db.execute(
            select(AgentRun)
            .options(selectinload(AgentRun.steps))
            .where(AgentRun.run_uuid == run_uuid)
        )
        run = result.scalar_one_or_none()
        if not run:
            return None
        steps = []
        for step in run.steps:
            intent = json.loads(step.intent_json) if step.intent_json else None
            steps.append(
                {
                    "step_order": step.step_order,
                    "description": step.description,
                    "status": step.status,
                    "position_intent": intent,
                    "purpose_review": json.loads(step.purpose_review_json)
                    if step.purpose_review_json
                    else None,
                }
            )
        return {
            "run_uuid": run.run_uuid,
            "exec_mode": "position",
            "case_id": run.source_case_id,
            "case_name": run.case_name,
            "status": run.status,
            "steps": steps,
        }


report_service = ReportService()
