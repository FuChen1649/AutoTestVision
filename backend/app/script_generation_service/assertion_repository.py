import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_assertion import CaseAssertionResult, CaseAssertionStep
from app.models.task import PlatformTask
from app.platform_service.repository import task_repository
from app.script_generation_service.assertion_detector import matched_assertion_keywords
from app.script_generation_service.verify_schemas import (
    AssertionDualConsistencyReview,
    AssertionVerifyResult,
    SampledStepAnnotationReview,
)


def parse_task_progress(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


class AssertionRepository:
    async def upsert_definition(
        self,
        db: AsyncSession,
        *,
        case_id: int,
        step_order: int,
        description: str,
    ) -> CaseAssertionStep:
        keywords = matched_assertion_keywords(description)
        result = await db.execute(
            select(CaseAssertionStep).where(
                CaseAssertionStep.case_id == case_id,
                CaseAssertionStep.step_order == step_order,
            )
        )
        row = result.scalar_one_or_none()
        keywords_json = json.dumps(keywords, ensure_ascii=False)
        if row is None:
            row = CaseAssertionStep(
                case_id=case_id,
                step_order=step_order,
                description=description,
                keywords_matched=keywords_json,
            )
            db.add(row)
        else:
            row.description = description
            row.keywords_matched = keywords_json
        await db.flush()
        return row

    async def list_definitions(self, db: AsyncSession, case_id: int) -> list[CaseAssertionStep]:
        result = await db.execute(
            select(CaseAssertionStep)
            .where(CaseAssertionStep.case_id == case_id)
            .order_by(CaseAssertionStep.step_order)
        )
        return list(result.scalars().all())

    async def save_result(
        self,
        db: AsyncSession,
        *,
        task_uuid: str,
        case_id: int,
        step_order: int,
        position_image: str | None,
        code_image: str | None,
        ui_xml: str | None,
        verify_result: AssertionVerifyResult,
    ) -> CaseAssertionResult:
        result = await db.execute(
            select(CaseAssertionResult).where(
                CaseAssertionResult.task_uuid == task_uuid,
                CaseAssertionResult.step_order == step_order,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = CaseAssertionResult(
                task_uuid=task_uuid,
                case_id=case_id,
                step_order=step_order,
            )
            db.add(row)
        row.position_image = position_image
        row.code_image = code_image
        row.ui_xml = ui_xml
        row.success = verify_result.success
        row.verify_result_json = verify_result.model_dump_json()
        await db.flush()
        return row

    async def list_results(self, db: AsyncSession, task_uuid: str) -> list[CaseAssertionResult]:
        result = await db.execute(
            select(CaseAssertionResult)
            .where(CaseAssertionResult.task_uuid == task_uuid)
            .order_by(CaseAssertionResult.step_order)
        )
        return list(result.scalars().all())


class ScriptGenProgressRepository:
    async def merge_progress(
        self, db: AsyncSession, task_uuid: str, patch: dict
    ) -> PlatformTask | None:
        task = await task_repository.get_by_uuid(db, task_uuid)
        if not task:
            return None
        progress = parse_task_progress(task.progress_json)
        progress.update(patch)
        task.progress_json = json.dumps(progress, ensure_ascii=False)
        await db.flush()
        return task

    async def append_sampled_review(
        self,
        db: AsyncSession,
        task: PlatformTask,
        review: SampledStepAnnotationReview,
    ) -> None:
        progress = parse_task_progress(task.progress_json)
        existing = progress.get("completion_sampled_reviews") or []
        merged = [item for item in existing if item.get("step_order") != review.step_order]
        merged.append(review.model_dump(mode="json"))
        merged.sort(key=lambda item: item.get("step_order", 0))
        progress["completion_sampled_reviews"] = merged
        task.progress_json = json.dumps(progress, ensure_ascii=False)
        await db.flush()

    async def append_assertion_dual_review(
        self,
        db: AsyncSession,
        task: PlatformTask,
        review: AssertionDualConsistencyReview,
    ) -> None:
        progress = parse_task_progress(task.progress_json)
        existing = progress.get("assertion_dual_reviews") or []
        merged = [item for item in existing if item.get("step_order") != review.step_order]
        merged.append(review.model_dump(mode="json"))
        merged.sort(key=lambda item: item.get("step_order", 0))
        progress["assertion_dual_reviews"] = merged
        task.progress_json = json.dumps(progress, ensure_ascii=False)
        await db.flush()


assertion_repository = AssertionRepository()
script_gen_progress_repository = ScriptGenProgressRepository()
