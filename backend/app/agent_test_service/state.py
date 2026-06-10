import operator
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from app.agent_test_service.schemas import ActionIntent, StepExecutionRecord, VerificationResult


def merge_records(
    left: list[StepExecutionRecord], right: list[StepExecutionRecord]
) -> list[StepExecutionRecord]:
    if not right:
        return left
    merged = {item.step_order: item for item in left}
    for item in right:
        merged[item.step_order] = item
    return [merged[key] for key in sorted(merged.keys())]


class HarnessAgentState(TypedDict, total=False):
    run_id: str
    case_id: int
    case_name: str
    serial: str | None
    status: str
    current_step_index: int
    total_steps: int
    retry_count: int
    max_retries: int
    error: str | None
    llm_provider: str | None
    enable_verifier: bool
    steps: Annotated[list[StepExecutionRecord], merge_records]
    current_description: str
    current_step_type: str
    current_reference_image: str | None
    current_reference_x: int | None
    current_reference_y: int | None
    current_reference_width: int | None
    current_reference_height: int | None
    before_image: str | None
    after_image: str | None
    screen_width: int
    screen_height: int
    intent: ActionIntent | None
    verification: VerificationResult | None
    should_continue: bool
    created_at: datetime
    updated_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
