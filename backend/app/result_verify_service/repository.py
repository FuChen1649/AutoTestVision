import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.repository import agent_repository
from app.agent_test_service.schemas import ActionIntent
from app.models.agent import AgentRun, AgentRunStep
from app.result_verify_service.schemas import StepPurposeReview


class ResultVerifyRepository:
    def parse_purpose_review(self, step: AgentRunStep) -> StepPurposeReview | None:
        if not step.purpose_review_json:
            return None
        try:
            return StepPurposeReview.model_validate_json(step.purpose_review_json)
        except Exception:
            return None

    def step_intent(self, step: AgentRunStep) -> ActionIntent | None:
        if not step.intent_json:
            return None
        return ActionIntent.model_validate_json(step.intent_json)

    async def save_purpose_review(
        self, db: AsyncSession, step: AgentRunStep, review: StepPurposeReview
    ) -> None:
        step.purpose_review_json = json.dumps(review.model_dump(mode="json"), ensure_ascii=False)
        await db.flush()

    async def get_run(self, db: AsyncSession, run_uuid: str) -> AgentRun | None:
        return await agent_repository.get_run_by_uuid(db, run_uuid)

    def collect_reviews(self, run: AgentRun) -> list[StepPurposeReview]:
        reviews: list[StepPurposeReview] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            review = self.parse_purpose_review(step)
            if review:
                reviews.append(review)
        return reviews


result_verify_repository = ResultVerifyRepository()
