from pydantic import BaseModel, Field


class DeviceInfo(BaseModel):
    serial: str
    model: str = ""
    product: str = ""
    screen_width: int = 0
    screen_height: int = 0
    connected: bool = True


class TapRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    serial: str | None = None


class SwipeRequest(BaseModel):
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)
    duration_ms: int = Field(default=300, ge=50, le=5000)
    serial: str | None = None


class LongPressRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    duration_ms: int = Field(default=800, ge=200, le=5000)
    serial: str | None = None


class AppInfo(BaseModel):
    package: str
    label: str
    category: str = "other"


class AppPermissionInfo(BaseModel):
    name: str
    label: str
    granted: bool | None = None
    revocable: bool = False
    group: str = "runtime"


class PermissionApplyRequest(BaseModel):
    selected_permissions: list[str] = Field(default_factory=list)
    serial: str | None = None


class PermissionApplyResult(BaseModel):
    package: str
    granted: list[str] = Field(default_factory=list)
    revoked: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
