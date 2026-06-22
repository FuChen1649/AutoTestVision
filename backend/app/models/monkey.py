from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MonkeySession(Base):
    __tablename__ = "monkey_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    serial: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_app_name: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="idle")
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, default=25)
    max_depth: Mapped[int] = mapped_column(Integer, default=6)
    current_node_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    navigation_stack_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    nodes: Mapped[list["MonkeyNode"]] = relationship(
        "MonkeyNode",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MonkeyNode.depth,MonkeyNode.id",
    )
    logs: Mapped[list["MonkeyLog"]] = relationship(
        "MonkeyLog",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MonkeyLog.created_at",
    )
    actions: Mapped[list["MonkeyActionRecord"]] = relationship(
        "MonkeyActionRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MonkeyActionRecord.step_index",
    )
    screen_actions: Mapped[list["MonkeyScreenAction"]] = relationship(
        "MonkeyScreenAction",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MonkeyScreenAction.screen_node_uuid,MonkeyScreenAction.action_no",
    )


class MonkeyNode(Base):
    __tablename__ = "monkey_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("monkey_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_node_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    node_type: Mapped[str] = mapped_column(Text, default="element")
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotated_screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    center_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="discovered")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["MonkeySession"] = relationship("MonkeySession", back_populates="nodes")


class MonkeyLog(Base):
    __tablename__ = "monkey_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("monkey_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_type: Mapped[str] = mapped_column(Text, default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["MonkeySession"] = relationship("MonkeySession", back_populates="logs")


class MonkeyActionRecord(Base):
    __tablename__ = "monkey_action_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("monkey_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    tool_name: Mapped[str] = mapped_column(Text, default="")
    node_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="ok")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["MonkeySession"] = relationship("MonkeySession", back_populates="actions")


class MonkeyScreenAction(Base):
    """屏幕上的编号操作（1/2/3…），用于迷宫式探索与路径回放。"""

    __tablename__ = "monkey_screen_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_uuid: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("monkey_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    screen_node_uuid: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    action_no: Mapped[int] = mapped_column(Integer, nullable=False)
    element_title: Mapped[str] = mapped_column(Text, default="")
    action_type: Mapped[str] = mapped_column(Text, default="tap")
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    center_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    swipe_to_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_dependency: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    result_screen_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    element_node_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay_script_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["MonkeySession"] = relationship("MonkeySession", back_populates="screen_actions")
