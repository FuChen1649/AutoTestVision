import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_service.repository import agent_repository
from app.models.agent import AgentRun, AgentRunStep
from app.models.agent_code import AgentCodeRun, AgentCodeRunStep
from app.models.task import PlatformTask
from app.result_verify_service.dual_analyzer import _format_code_action, _format_position_action
from app.result_verify_service.schemas import DualStepVerifyReview


def parse_task_progress(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


class DualVerifyRepository:
    async def get_task(self, db: AsyncSession, task_uuid: str) -> PlatformTask | None:
        result = await db.execute(
            select(PlatformTask).where(PlatformTask.task_uuid == task_uuid)
        )
        task = result.scalar_one_or_none()
        if not task or task.task_type != "script_generation":
            return None
        return task

    async def load_dual_runs(
        self, db: AsyncSession, task: PlatformTask
    ) -> tuple[AgentRun, AgentCodeRun]:
        progress = parse_task_progress(task.progress_json)
        pos_uuid = progress.get("position_run_uuid")
        code_uuid = progress.get("code_run_uuid")
        if not pos_uuid or not code_uuid:
            raise RuntimeError("双脚本任务缺少 Position / Code 运行记录")
        pos_run = await agent_repository.get_run_by_uuid(db, str(pos_uuid))
        code_run = await agent_code_repository.get_run_by_uuid(db, str(code_uuid))
        if not pos_run or not code_run:
            raise RuntimeError("双脚本子运行记录不存在")
        return pos_run, code_run

    def collect_reviews(self, task: PlatformTask) -> list[DualStepVerifyReview]:
        progress = parse_task_progress(task.progress_json)
        raw_reviews = progress.get("dual_reviews") or []
        reviews: list[DualStepVerifyReview] = []
        for item in raw_reviews:
            try:
                reviews.append(DualStepVerifyReview.model_validate(item))
            except Exception:
                continue
        reviews.sort(key=lambda row: row.step_order)
        return reviews

    async def save_review(
        self, db: AsyncSession, task: PlatformTask, review: DualStepVerifyReview
    ) -> None:
        progress = parse_task_progress(task.progress_json)
        existing = progress.get("dual_reviews") or []
        merged = [item for item in existing if item.get("step_order") != review.step_order]
        merged.append(review.model_dump(mode="json"))
        merged.sort(key=lambda item: item.get("step_order", 0))
        progress["dual_reviews"] = merged
        task.progress_json = json.dumps(progress, ensure_ascii=False)
        await db.flush()

    def iter_step_pairs(
        self, pos_run: AgentRun, code_run: AgentCodeRun
    ) -> list[tuple[AgentRunStep, AgentCodeRunStep]]:
        pos_map = {step.step_order: step for step in pos_run.steps}
        code_map = {step.step_order: step for step in code_run.steps}
        orders = sorted(set(pos_map) & set(code_map))
        return [(pos_map[order], code_map[order]) for order in orders]

    def step_images(
        self, pos_step: AgentRunStep, code_step: AgentCodeRunStep
    ) -> tuple[str, str, str, str] | None:
        pos_before = pos_step.before_image_annotated or pos_step.before_image
        pos_after = pos_step.after_image
        code_before = code_step.before_image_annotated or code_step.before_image
        code_after = code_step.after_image
        if not all((pos_before, pos_after, code_before, code_after)):
            return None
        return pos_before, pos_after, code_before, code_after

    def step_actions(self, pos_step: AgentRunStep, code_step: AgentCodeRunStep) -> tuple[str, str]:
        return (
            _format_position_action(pos_step.intent_json),
            _format_code_action(code_step.generated_code_json),
        )


dual_verify_repository = DualVerifyRepository()
