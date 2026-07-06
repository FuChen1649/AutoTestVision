from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformTaskLog(Base):
    """平台任务级日志（双脚本生成等无独立 agent_run 的流程）。"""

    __tablename__ = "platform_task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_type: Mapped[str] = mapped_column(Text, default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
