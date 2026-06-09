from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
