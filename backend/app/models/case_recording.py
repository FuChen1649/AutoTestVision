from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CaseRecordingSession(Base):
    __tablename__ = "case_recording_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_name: Mapped[str] = mapped_column(Text, default="录制 Case")
    status: Mapped[str] = mapped_column(Text, default="recording")
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    generated_steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["CaseRecordingEvent"]] = relationship(
        "CaseRecordingEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CaseRecordingEvent.step_order",
    )
    logs: Mapped[list["CaseRecordingLog"]] = relationship(
        "CaseRecordingLog",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CaseRecordingLog.id",
    )


class CaseRecordingLog(Base):
    __tablename__ = "case_recording_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("case_recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    log_type: Mapped[str] = mapped_column(Text, default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["CaseRecordingSession"] = relationship("CaseRecordingSession", back_populates="logs")


class CaseRecordingEvent(Base):
    __tablename__ = "case_recording_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("case_recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str] = mapped_column(Text, default="tap")
    x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    x2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_xml_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_xml_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    device_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["CaseRecordingSession"] = relationship("CaseRecordingSession", back_populates="events")
