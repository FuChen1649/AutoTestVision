from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FlywheelSample(Base):
    """从 agent 执行步骤同步的可训练样本。"""

    __tablename__ = "flywheel_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_run_uuid: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    step_type: Mapped[str] = mapped_column(Text, default="natural")
    step_status: Mapped[str] = mapped_column(Text, default="pending")
    cleaning_status: Mapped[str] = mapped_column(Text, default="raw", index=True)
    auto_verification_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    auto_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    has_before_image: Mapped[bool] = mapped_column(Boolean, default=False)
    has_after_image: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaning_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    annotation: Mapped["FlywheelAnnotation | None"] = relationship(
        "FlywheelAnnotation", back_populates="sample", uselist=False, cascade="all, delete-orphan"
    )


class FlywheelAnnotation(Base):
    """人工标注 / 黄金标签。"""

    __tablename__ = "flywheel_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("flywheel_samples.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    label_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotated_by: Mapped[str] = mapped_column(Text, default="human")
    is_golden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sample: Mapped["FlywheelSample"] = relationship("FlywheelSample", back_populates="annotation")


class FlywheelDataset(Base):
    __tablename__ = "flywheel_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    dataset_type: Mapped[str] = mapped_column(Text, default="train")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["FlywheelDatasetItem"]] = relationship(
        "FlywheelDatasetItem", back_populates="dataset", cascade="all, delete-orphan"
    )


class FlywheelDatasetItem(Base):
    __tablename__ = "flywheel_dataset_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("flywheel_datasets.id", ondelete="CASCADE"))
    sample_id: Mapped[int] = mapped_column(ForeignKey("flywheel_samples.id", ondelete="CASCADE"))

    dataset: Mapped["FlywheelDataset"] = relationship("FlywheelDataset", back_populates="items")


class FlywheelRagDocument(Base):
    __tablename__ = "flywheel_rag_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("flywheel_datasets.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_sample_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlywheelTrainingJob(Base):
    __tablename__ = "flywheel_training_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("flywheel_datasets.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlywheelEvalJob(Base):
    __tablename__ = "flywheel_eval_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("flywheel_datasets.id", ondelete="CASCADE"))
    training_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("flywheel_training_jobs.id", ondelete="SET NULL"), nullable=True
    )
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
