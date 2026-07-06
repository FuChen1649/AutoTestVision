from datetime import datetime
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseStepCreate(BaseModel):
    description: str = ""
    step_order: int = 0
    step_type: str = "natural"
    screen_image: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    selection_x: int | None = None
    selection_y: int | None = None
    selection_width: int | None = None
    selection_height: int | None = None
    metadata_json: dict | None = None


class CaseStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    step_order: int
    step_type: str = "natural"
    description: str
    screen_image: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    selection_x: int | None = None
    selection_y: int | None = None
    selection_width: int | None = None
    selection_height: int | None = None
    metadata_json: dict | None = None
    position_script_json: dict | None = None
    code_script_json: dict | None = None
    script_generated_at: datetime | None = None
    script_status: str | None = None

    @field_validator("metadata_json", "position_script_json", "code_script_json", mode="before")
    @classmethod
    def parse_json_fields(cls, value: object) -> dict | None:
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return None


class CaseCreate(BaseModel):
    name: str = "未命名 Case"
    script_content: str = ""
    steps: list[CaseStepCreate] = Field(default_factory=list)


class CaseUpdate(BaseModel):
    name: str | None = None
    script_content: str | None = None
    steps: list[CaseStepCreate] | None = None


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    script_content: str
    created_at: datetime
    updated_at: datetime
    steps: list[CaseStepResponse] = Field(default_factory=list)


class CaseListItemResponse(BaseModel):
    id: int
    name: str
    script_content: str = ""
    step_count: int = 0
    script_status: str | None = None
    last_run_status: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseListPageResponse(BaseModel):
    items: list[CaseListItemResponse]
    total: int
    page: int
    size: int
