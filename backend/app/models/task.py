from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformTask(Base):
    __tablename__ = "platform_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    exec_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    case_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    parent_task_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
