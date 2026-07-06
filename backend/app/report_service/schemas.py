from datetime import datetime

from pydantic import BaseModel, Field


class ReportSummaryItem(BaseModel):
    report_id: str
    report_type: str
    exec_mode: str
    status: str
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    completed_cases: int = 0
    serial: str | None = None
    case_id: int | None = None
    case_name: str | None = None
    run_uuid: str | None = None
    position_run_uuid: str | None = None
    code_run_uuid: str | None = None
    created_at: datetime
    updated_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportSummaryItem]
    total: int


class ReportStepSummary(BaseModel):
    step_order: int
    description: str
    status: str
    position_intent: dict | None = None
    code_line: str | None = None
    purpose_review: dict | None = None


class ReportDetailResponse(BaseModel):
    report_id: str
    report_type: str
    exec_mode: str
    status: str
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    completed_cases: int = 0
    case_id: int | None = None
    case_name: str | None = None
    run_uuid: str | None = None
    case_results: list[dict] = Field(default_factory=list)
    dual_reviews: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
