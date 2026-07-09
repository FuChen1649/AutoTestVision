from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CaseAssertionStep(Base):
    """Case 级断言步骤定义（由步骤描述关键词自动识别并持久化）。"""

    __tablename__ = "case_assertion_steps"
    __table_args__ = (UniqueConstraint("case_id", "step_order", name="uq_case_assertion_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    keywords_matched: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaseAssertionResult(Base):
    """单次双脚本生成任务中某断言步骤的验证结果（含截图与 XML）。"""

    __tablename__ = "case_assertion_results"
    __table_args__ = (
        UniqueConstraint("task_uuid", "step_order", name="uq_assertion_result_task_step"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    position_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    ui_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
