from datetime import datetime, timezone
from typing import Annotated, TypedDict

from app.agent_test_code_service.schemas import CodeStepExecutionRecord, GeneratedStepCode
from app.agent_test_service.schemas import VerificationResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def merge_records(left: list, right: list) -> list:
    if not right:
        return left
    if len(right) == 1 and left:
        updated = list(left)
        record = right[0]
        for index, item in enumerate(updated):
            if item.step_order == record.step_order:
                updated[index] = record
                return updated
    return right or left


class CodeHarnessState(TypedDict, total=False):
    run_id: str
    case_id: int
    case_name: str
    script_content: str
    serial: str | None
    status: str
    current_step_index: int
    total_steps: int
    retry_count: int
    max_retries: int
    error: str | None
    llm_provider: str | None
    enable_verifier: bool
    steps: Annotated[list[CodeStepExecutionRecord], merge_records]
    current_description: str
    current_step_type: str
    before_image: str | None
    after_image: str | None
    ui_xml: str | None
    screen_width: int
    screen_height: int
    generated_code: GeneratedStepCode | None
    verification: VerificationResult | None
    should_continue: bool
    created_at: datetime
    updated_at: datetime
