from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssertionVerifyResult(BaseModel):
    step_order: int
    success: bool = False
    confidence: float = Field(ge=0, le=1, default=0.0)
    reasoning: str = ""
    model: str | None = None
    reviewed_at: datetime


class SampledStepAnnotationReview(BaseModel):
    step_order: int
    section: Literal["begin", "middle", "end"]
    annotation_correct: bool = False
    flow_correct: bool = False
    reasoning: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)
    model: str | None = None
    reviewed_at: datetime


class AssertionDualConsistencyReview(BaseModel):
    step_order: int
    consistent: bool = False
    reasoning: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)
    model: str | None = None
    reviewed_at: datetime


class CompletionVerifySummary(BaseModel):
    sampled_reviews: list[SampledStepAnnotationReview] = Field(default_factory=list)
    assertion_dual_reviews: list[AssertionDualConsistencyReview] = Field(default_factory=list)
