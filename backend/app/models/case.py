from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="未命名 Case")
    script_content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["CaseStep"]] = relationship(
        "CaseStep", back_populates="case", cascade="all, delete-orphan", order_by="CaseStep.step_order"
    )


class CaseStep(Base):
    __tablename__ = "case_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(Text, default="natural")
    description: Mapped[str] = mapped_column(Text, default="")
    screen_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="steps")
