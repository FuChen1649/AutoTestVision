from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentCodeRun(Base):
    __tablename__ = "agent_code_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_code_batch_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(Text, default="")
    script_content: Mapped[str] = mapped_column(Text, default="")
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    enable_verifier: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["AgentCodeRunStep"]] = relationship(
        "AgentCodeRunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentCodeRunStep.step_order",
    )
    logs: Mapped[list["AgentCodeLog"]] = relationship(
        "AgentCodeLog", back_populates="run", cascade="all, delete-orphan", order_by="AgentCodeLog.created_at"
    )
    attempts: Mapped[list["AgentCodeRunStepAttempt"]] = relationship(
        "AgentCodeRunStepAttempt",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentCodeRunStepAttempt.created_at",
    )


class AgentCodeRunStep(Base):
    __tablename__ = "agent_code_run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_code_runs.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(Text, default="natural")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="pending")
    reference_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_image_annotated: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    ui_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_code_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["AgentCodeRun"] = relationship("AgentCodeRun", back_populates="steps")


class AgentCodeLog(Base):
    __tablename__ = "agent_code_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_code_runs.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_type: Mapped[str] = mapped_column(Text, default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["AgentCodeRun"] = relationship("AgentCodeRun", back_populates="logs")


class AgentCodeRunStepAttempt(Base):
    __tablename__ = "agent_code_run_step_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_code_runs.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    before_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_code_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["AgentCodeRun"] = relationship("AgentCodeRun", back_populates="attempts")


class AgentCodeBatchRun(Base):
    __tablename__ = "agent_code_batch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    enable_verifier: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    case_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    results: Mapped[list["AgentCodeBatchResult"]] = relationship(
        "AgentCodeBatchResult", back_populates="batch", cascade="all, delete-orphan"
    )


class AgentCodeBatchResult(Base):
    __tablename__ = "agent_code_batch_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("agent_code_batch_runs.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(Text, default="")
    run_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["AgentCodeBatchRun"] = relationship("AgentCodeBatchRun", back_populates="results")
