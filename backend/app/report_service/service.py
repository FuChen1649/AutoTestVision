import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import AgentBatchRun, AgentRun
from app.models.agent_code import AgentCodeBatchRun, AgentCodeRun
from app.models.task import PlatformTask
from app.report_service.schemas import ReportDetailResponse, ReportListResponse, ReportSummaryItem

_SUCCESS_STATUSES = {"completed", "success"}
_TERMINAL_STATUSES = {"completed", "success", "failed", "cancelled"}


def _run_passed(status: str) -> bool:
    return status in _SUCCESS_STATUSES


def _run_failed(status: str) -> bool:
    return status == "failed"


def _run_completed(status: str) -> bool:
    return status in _TERMINAL_STATUSES


def _parse_task_progress(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def _script_gen_child_run_uuids(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(PlatformTask).where(PlatformTask.task_type == "script_generation")
    )
    uuids: set[str] = set()
    for task in result.scalars().all():
        progress = _parse_task_progress(task.progress_json)
        if progress.get("position_run_uuid"):
            uuids.add(str(progress["position_run_uuid"]))
        if progress.get("code_run_uuid"):
            uuids.add(str(progress["code_run_uuid"]))
    return uuids


def _run_summary_from_agent_run(run: AgentRun) -> ReportSummaryItem:
    return ReportSummaryItem(
        report_id=run.run_uuid,
        report_type="single",
        exec_mode="position",
        status=run.status,
        total_cases=1,
        passed_cases=1 if _run_passed(run.status) else 0,
        failed_cases=1 if _run_failed(run.status) else 0,
        completed_cases=1 if _run_completed(run.status) else 0,
        serial=run.serial,
        case_id=run.source_case_id,
        case_name=run.case_name,
        run_uuid=run.run_uuid,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _run_summary_from_code_run(run: AgentCodeRun) -> ReportSummaryItem:
    return ReportSummaryItem(
        report_id=run.run_uuid,
        report_type="single",
        exec_mode="code",
        status=run.status,
        total_cases=1,
        passed_cases=1 if _run_passed(run.status) else 0,
        failed_cases=1 if _run_failed(run.status) else 0,
        completed_cases=1 if _run_completed(run.status) else 0,
        serial=run.serial,
        case_id=run.source_case_id,
        case_name=run.case_name,
        run_uuid=run.run_uuid,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _count_passed_steps(steps: list) -> int:
    return sum(1 for step in steps if step.status in _SUCCESS_STATUSES)


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
        child_run_uuids = await _script_gen_child_run_uuids(db)

        if exec_mode in (None, "dual", "all"):
            dual_tasks = await db.execute(
                select(PlatformTask)
                .where(PlatformTask.task_type == "script_generation")
                .order_by(PlatformTask.created_at.desc())
            )
            for task in dual_tasks.scalars().all():
                progress = _parse_task_progress(task.progress_json)
                pos_uuid = progress.get("position_run_uuid")
                code_uuid = progress.get("code_run_uuid")
                items.append(
                    ReportSummaryItem(
                        report_id=task.task_uuid,
                        report_type="dual",
                        exec_mode="dual",
                        status=task.status,
                        total_cases=1,
                        passed_cases=1 if task.status in _SUCCESS_STATUSES else 0,
                        failed_cases=1 if task.status == "failed" else 0,
                        completed_cases=1 if _run_completed(task.status) else 0,
                        serial=task.serial,
                        case_id=task.source_case_id,
                        case_name=task.case_name,
                        position_run_uuid=pos_uuid,
                        code_run_uuid=code_uuid,
                        created_at=task.created_at,
                        updated_at=task.updated_at,
                    )
                )

        if exec_mode in (None, "position", "all"):
            pos_batches = await db.execute(
                select(AgentBatchRun).order_by(AgentBatchRun.created_at.desc())
            )
            for batch in pos_batches.scalars().all():
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

            pos_runs = await db.execute(
                select(AgentRun)
                .where(AgentRun.batch_id.is_(None))
                .order_by(AgentRun.created_at.desc())
            )
            for run in pos_runs.scalars().all():
                if run.run_uuid in child_run_uuids:
                    continue
                items.append(_run_summary_from_agent_run(run))

        if exec_mode in (None, "code", "all"):
            code_batches = await db.execute(
                select(AgentCodeBatchRun)
                .options(selectinload(AgentCodeBatchRun.results))
                .order_by(AgentCodeBatchRun.created_at.desc())
            )
            for batch in code_batches.scalars().all():
                case_ids = json.loads(batch.case_ids_json or "[]")
                results = list(batch.results)
                total = len(case_ids) or len(results)
                passed = sum(1 for item in results if _run_passed(item.status))
                failed = sum(1 for item in results if _run_failed(item.status))
                completed = sum(1 for item in results if _run_completed(item.status))
                items.append(
                    ReportSummaryItem(
                        report_id=batch.batch_uuid,
                        report_type="batch",
                        exec_mode="code",
                        status=batch.status,
                        total_cases=total,
                        passed_cases=passed,
                        failed_cases=failed,
                        completed_cases=completed,
                        serial=None,
                        created_at=batch.created_at,
                        updated_at=batch.updated_at,
                    )
                )

            code_runs = await db.execute(
                select(AgentCodeRun)
                .where(AgentCodeRun.batch_id.is_(None))
                .order_by(AgentCodeRun.created_at.desc())
            )
            for run in code_runs.scalars().all():
                if run.run_uuid in child_run_uuids:
                    continue
                items.append(_run_summary_from_code_run(run))

        items.sort(key=lambda item: item.created_at, reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return ReportListResponse(items=page, total=total)

    async def get_report(
        self, db: AsyncSession, report_id: str, exec_mode: str = "position"
    ) -> ReportDetailResponse | None:
        if exec_mode in ("dual", "all"):
            dual_detail = await self._get_dual_script_report(db, report_id)
            if dual_detail:
                return dual_detail

        if exec_mode == "code":
            batch_detail = await self._get_code_batch_report(db, report_id)
            if batch_detail:
                return batch_detail
            return await self._get_code_single_report(db, report_id)

        batch_detail = await self._get_position_batch_report(db, report_id)
        if batch_detail:
            return batch_detail
        return await self._get_position_single_report(db, report_id)

    async def _get_dual_script_report(
        self, db: AsyncSession, task_uuid: str
    ) -> ReportDetailResponse | None:
        result = await db.execute(
            select(PlatformTask).where(PlatformTask.task_uuid == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task or task.task_type != "script_generation":
            return None

        progress = _parse_task_progress(task.progress_json)
        pos_uuid = progress.get("position_run_uuid")
        code_uuid = progress.get("code_run_uuid")
        case_results: list[dict] = []

        if pos_uuid:
            pos_detail = await self._get_position_single_report(db, str(pos_uuid))
            if pos_detail and pos_detail.case_results:
                row = dict(pos_detail.case_results[0])
                row["exec_mode"] = "position"
                row["path_label"] = "Position"
                case_results.append(row)

        if code_uuid:
            code_detail = await self._get_code_single_report(db, str(code_uuid))
            if code_detail and code_detail.case_results:
                row = dict(code_detail.case_results[0])
                row["exec_mode"] = "code"
                row["path_label"] = "Code"
                case_results.append(row)

        dual_reviews = progress.get("dual_reviews") or []

        return ReportDetailResponse(
            report_id=task.task_uuid,
            report_type="dual",
            exec_mode="dual",
            status=task.status,
            total_cases=1,
            passed_cases=1 if task.status in _SUCCESS_STATUSES else 0,
            failed_cases=1 if task.status == "failed" else 0,
            completed_cases=1 if _run_completed(task.status) else 0,
            case_id=task.source_case_id,
            case_name=task.case_name,
            case_results=case_results,
            dual_reviews=dual_reviews,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def _get_position_batch_report(
        self, db: AsyncSession, report_id: str
    ) -> ReportDetailResponse | None:
        result = await db.execute(
            select(AgentBatchRun)
            .options(selectinload(AgentBatchRun.results))
            .where(AgentBatchRun.batch_uuid == report_id)
        )
        batch = result.scalar_one_or_none()
        if not batch:
            return None
        case_results = [
            {
                "case_id": item.case_id,
                "case_name": item.case_name,
                "status": item.status,
                "run_uuid": item.run_uuid,
                "total_steps": item.total_steps,
                "passed_steps": item.passed_steps,
                "error": item.error,
            }
            for item in batch.results
        ]
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

    async def _get_code_batch_report(
        self, db: AsyncSession, report_id: str
    ) -> ReportDetailResponse | None:
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
            total_steps = 0
            passed_steps = 0
            if item.run_uuid:
                run_result = await db.execute(
                    select(AgentCodeRun)
                    .options(selectinload(AgentCodeRun.steps))
                    .where(AgentCodeRun.run_uuid == item.run_uuid)
                )
                run = run_result.scalar_one_or_none()
                if run:
                    total_steps = run.total_steps
                    passed_steps = _count_passed_steps(run.steps)
            case_results.append(
                {
                    "case_id": item.case_id,
                    "case_name": item.case_name,
                    "status": item.status,
                    "run_uuid": item.run_uuid,
                    "total_steps": total_steps,
                    "passed_steps": passed_steps,
                    "error": item.error,
                }
            )

        case_ids = json.loads(batch.case_ids_json or "[]")
        total = len(case_ids) or len(case_results)
        passed = sum(1 for item in case_results if _run_passed(str(item["status"])))
        failed = sum(1 for item in case_results if _run_failed(str(item["status"])))
        completed = sum(1 for item in case_results if _run_completed(str(item["status"])))

        return ReportDetailResponse(
            report_id=batch.batch_uuid,
            report_type="batch",
            exec_mode="code",
            status=batch.status,
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            completed_cases=completed,
            case_results=case_results,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    async def _get_position_single_report(
        self, db: AsyncSession, run_uuid: str
    ) -> ReportDetailResponse | None:
        result = await db.execute(
            select(AgentRun)
            .options(selectinload(AgentRun.steps))
            .where(AgentRun.run_uuid == run_uuid)
        )
        run = result.scalar_one_or_none()
        if not run:
            return None
        passed_steps = _count_passed_steps(run.steps)
        return ReportDetailResponse(
            report_id=run.run_uuid,
            report_type="single",
            exec_mode="position",
            status=run.status,
            total_cases=1,
            passed_cases=1 if _run_passed(run.status) else 0,
            failed_cases=1 if _run_failed(run.status) else 0,
            completed_cases=1 if _run_completed(run.status) else 0,
            case_id=run.source_case_id,
            case_name=run.case_name,
            run_uuid=run.run_uuid,
            case_results=[
                {
                    "case_id": run.source_case_id,
                    "case_name": run.case_name,
                    "status": run.status,
                    "run_uuid": run.run_uuid,
                    "total_steps": run.total_steps,
                    "passed_steps": passed_steps,
                    "error": run.error,
                }
            ],
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    async def _get_code_single_report(
        self, db: AsyncSession, run_uuid: str
    ) -> ReportDetailResponse | None:
        result = await db.execute(
            select(AgentCodeRun)
            .options(selectinload(AgentCodeRun.steps))
            .where(AgentCodeRun.run_uuid == run_uuid)
        )
        run = result.scalar_one_or_none()
        if not run:
            return None
        passed_steps = _count_passed_steps(run.steps)
        return ReportDetailResponse(
            report_id=run.run_uuid,
            report_type="single",
            exec_mode="code",
            status=run.status,
            total_cases=1,
            passed_cases=1 if _run_passed(run.status) else 0,
            failed_cases=1 if _run_failed(run.status) else 0,
            completed_cases=1 if _run_completed(run.status) else 0,
            case_id=run.source_case_id,
            case_name=run.case_name,
            run_uuid=run.run_uuid,
            case_results=[
                {
                    "case_id": run.source_case_id,
                    "case_name": run.case_name,
                    "status": run.status,
                    "run_uuid": run.run_uuid,
                    "total_steps": run.total_steps,
                    "passed_steps": passed_steps,
                    "error": run.error,
                }
            ],
            created_at=run.created_at,
            updated_at=run.updated_at,
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
                        "before_image": step.before_image,
                        "after_image": step.after_image,
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
            .options(selectinload(AgentRun.steps), selectinload(AgentRun.attempts))
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
                    "before_image": step.before_image,
                    "after_image": step.after_image,
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
