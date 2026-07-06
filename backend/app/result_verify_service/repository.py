import json
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_code_service.schemas import GeneratedStepCode
from app.agent_test_service.repository import agent_repository
from app.agent_test_service.schemas import ActionIntent
from app.models.agent import AgentRun, AgentRunStep
from app.models.agent_code import AgentCodeBatchRun, AgentCodeRun, AgentCodeRunStep
from app.result_verify_service.schemas import StepPurposeReview

ExecMode = Literal["position", "code"]


class ResultVerifyRepository:
    def parse_purpose_review_position(self, step: AgentRunStep) -> StepPurposeReview | None:
        if not step.purpose_review_json:
            return None
        try:
            return StepPurposeReview.model_validate_json(step.purpose_review_json)
        except Exception:
            return None

    def parse_purpose_review_code(self, step: AgentCodeRunStep) -> StepPurposeReview | None:
        if not step.purpose_review_json:
            return None
        try:
            return StepPurposeReview.model_validate_json(step.purpose_review_json)
        except Exception:
            return None

    def step_intent_position(self, step: AgentRunStep) -> ActionIntent | None:
        if not step.intent_json:
            return None
        return ActionIntent.model_validate_json(step.intent_json)

    def step_intent_code(self, step: AgentCodeRunStep) -> ActionIntent | None:
        if not step.generated_code_json:
            return None
        try:
            generated = GeneratedStepCode.model_validate_json(step.generated_code_json)
        except Exception:
            return None
        if not generated.code_line:
            return None
        return ActionIntent(
            action="tap",
            confidence=generated.confidence,
            reasoning=generated.code_line,
        )

    async def save_purpose_review_position(
        self, db: AsyncSession, step: AgentRunStep, review: StepPurposeReview
    ) -> None:
        step.purpose_review_json = json.dumps(review.model_dump(mode="json"), ensure_ascii=False)
        await db.flush()

    async def save_purpose_review_code(
        self, db: AsyncSession, step: AgentCodeRunStep, review: StepPurposeReview
    ) -> None:
        step.purpose_review_json = json.dumps(review.model_dump(mode="json"), ensure_ascii=False)
        await db.flush()

    async def resolve_run(
        self, db: AsyncSession, run_uuid: str
    ) -> tuple[ExecMode, AgentRun | AgentCodeRun] | tuple[None, None]:
        position_run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if position_run:
            return "position", position_run
        code_run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if code_run:
            return "code", code_run
        return None, None

    async def get_position_run(self, db: AsyncSession, run_uuid: str) -> AgentRun | None:
        return await agent_repository.get_run_by_uuid(db, run_uuid)

    async def get_code_run(self, db: AsyncSession, run_uuid: str) -> AgentCodeRun | None:
        return await agent_code_repository.get_run_by_uuid(db, run_uuid)

    async def get_position_batch(self, db: AsyncSession, batch_uuid: str):
        return await agent_repository.get_batch_by_uuid(db, batch_uuid)

    async def get_code_batch(self, db: AsyncSession, batch_uuid: str) -> AgentCodeBatchRun | None:
        return await agent_code_repository.get_batch_by_uuid(db, batch_uuid)

    def collect_reviews_position(self, run: AgentRun) -> list[StepPurposeReview]:
        reviews: list[StepPurposeReview] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            review = self.parse_purpose_review_position(step)
            if review:
                reviews.append(review)
        return reviews

    def collect_reviews_code(self, run: AgentCodeRun) -> list[StepPurposeReview]:
        reviews: list[StepPurposeReview] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            review = self.parse_purpose_review_code(step)
            if review:
                reviews.append(review)
        return reviews


result_verify_repository = ResultVerifyRepository()
