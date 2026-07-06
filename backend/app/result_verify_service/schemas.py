from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.agent_test_service.schemas import RunStateResponse


class StepPurposeReview(BaseModel):
    step_order: int
    purpose: str = ""
    reasoning: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)
    model: str | None = None
    reviewed_at: datetime


class DualStepVerifyReview(BaseModel):
    step_order: int
    consistent: bool = False
    before_match: bool = False
    after_match: bool = False
    purpose: str = ""
    reasoning: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)
    model: str | None = None
    reviewed_at: datetime


class DualVerifyResponse(BaseModel):
    task_id: str
    case_name: str
    reviews: list[DualStepVerifyReview] = Field(default_factory=list)


class RunPurposeReviewResponse(BaseModel):
    run_id: str
    case_name: str
    reviews: list[StepPurposeReview] = Field(default_factory=list)


class BatchPurposeReviewResponse(BaseModel):
    batch_id: str
    runs: list[RunPurposeReviewResponse] = Field(default_factory=list)


class VerifyRunRequest(BaseModel):
    llm_provider: str | None = None


class VerifyBatchRequest(BaseModel):
    llm_provider: str | None = None


class VerifyStreamEvent(BaseModel):
    type: str
    exec_mode: Literal["position", "code", "dual"] | None = None
    batch_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    case_name: str | None = None
    step_order: int | None = None
    review: StepPurposeReview | None = None
    dual_review: DualStepVerifyReview | None = None
    run: RunStateResponse | None = None
    message: str | None = None
