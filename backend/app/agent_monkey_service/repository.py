from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_monkey_service.schemas import (
    BBox,
    Center,
    MonkeyActionRecordResponse,
    MonkeyLogItem,
    MonkeyNodeResponse,
    MonkeySessionResponse,
    MonkeyTreeResponse,
)
from app.models.monkey import MonkeyActionRecord, MonkeyLog, MonkeyNode, MonkeySession

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MONKEY_DATA_ROOT = BACKEND_ROOT / "data" / "monkey"


def monkey_session_dir(session_uuid: str) -> Path:
    path = MONKEY_DATA_ROOT / session_uuid
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshot_to_url(session_uuid: str, filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/api/agent-monkey/sessions/{session_uuid}/screenshots/{filename}"


class MonkeyRepository:
    async def create_session(
        self,
        db: AsyncSession,
        *,
        serial: str | None,
        target_app_name: str,
        llm_provider: str | None,
        max_steps: int,
        max_depth: int,
    ) -> MonkeySession:
        session = MonkeySession(
            session_uuid=str(uuid.uuid4()),
            serial=serial,
            target_app_name=target_app_name.strip(),
            status="idle",
            llm_provider=llm_provider,
            max_steps=max_steps,
            max_depth=max_depth,
            navigation_stack_json="[]",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        monkey_session_dir(session.session_uuid)
        return session

    async def get_session(self, db: AsyncSession, session_uuid: str) -> MonkeySession | None:
        result = await db.execute(
            select(MonkeySession)
            .options(
                selectinload(MonkeySession.nodes),
                selectinload(MonkeySession.logs),
                selectinload(MonkeySession.actions),
            )
            .where(MonkeySession.session_uuid == session_uuid)
        )
        return result.scalar_one_or_none()

    async def list_sessions(self, db: AsyncSession, limit: int = 20) -> list[MonkeySession]:
        result = await db.execute(
            select(MonkeySession).order_by(MonkeySession.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def update_session(self, db: AsyncSession, session: MonkeySession, **fields) -> MonkeySession:
        for key, value in fields.items():
            setattr(session, key, value)
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    async def add_log(
        self,
        db: AsyncSession,
        session: MonkeySession,
        message: str,
        *,
        log_type: str = "system",
        step_index: int | None = None,
        detail: dict | None = None,
    ) -> MonkeyLog:
        log = MonkeyLog(
            session_id=session.id,
            step_index=step_index,
            log_type=log_type,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(log)
        await db.flush()
        return log

    async def add_action(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        tool_name: str,
        node_uuid: str | None = None,
        x: int | None = None,
        y: int | None = None,
        title: str | None = None,
        result: str = "ok",
        detail: dict | None = None,
    ) -> MonkeyActionRecord:
        record = MonkeyActionRecord(
            session_id=session.id,
            step_index=step_index,
            tool_name=tool_name,
            node_uuid=node_uuid,
            x=x,
            y=y,
            title=title,
            result=result,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(record)
        await db.flush()
        return record

    async def add_node(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        node_uuid: str | None = None,
        parent_node_uuid: str | None,
        node_type: str,
        title: str,
        description: str | None = None,
        screenshot_path: str | None = None,
        annotated_screenshot_path: str | None = None,
        bbox: BBox | None = None,
        center: Center | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        screen_fingerprint: str | None = None,
        status: str = "discovered",
        depth: int = 0,
        confidence: float = 0.0,
        metadata: dict | None = None,
    ) -> MonkeyNode:
        node = MonkeyNode(
            node_uuid=node_uuid or str(uuid.uuid4()),
            session_id=session.id,
            parent_node_uuid=parent_node_uuid,
            node_type=node_type,
            title=title,
            description=description,
            screenshot_path=screenshot_path,
            annotated_screenshot_path=annotated_screenshot_path,
            bbox_json=bbox.model_dump_json() if bbox else None,
            center_json=center.model_dump_json() if center else None,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=screen_fingerprint,
            status=status,
            depth=depth,
            confidence=confidence,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        )
        db.add(node)
        await db.flush()
        return node

    async def get_node(self, db: AsyncSession, session: MonkeySession, node_uuid: str) -> MonkeyNode | None:
        result = await db.execute(
            select(MonkeyNode).where(
                MonkeyNode.session_id == session.id,
                MonkeyNode.node_uuid == node_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def delete_session(self, db: AsyncSession, session: MonkeySession) -> None:
        await db.delete(session)
        await db.commit()

    def save_screenshot_bytes(self, session_uuid: str, name: str, image_bytes: bytes) -> str:
        path = monkey_session_dir(session_uuid) / name
        path.write_bytes(image_bytes)
        return name

    def load_screenshot_bytes(self, session_uuid: str, filename: str) -> bytes:
        path = monkey_session_dir(session_uuid) / filename
        if not path.exists():
            raise FileNotFoundError(filename)
        return path.read_bytes()

    def node_to_response(self, session_uuid: str, node: MonkeyNode) -> MonkeyNodeResponse:
        bbox = None
        center = None
        if node.bbox_json:
            bbox = BBox.model_validate_json(node.bbox_json)
        if node.center_json:
            center = Center.model_validate_json(node.center_json)
        return MonkeyNodeResponse(
            node_uuid=node.node_uuid,
            parent_node_uuid=node.parent_node_uuid,
            node_type=node.node_type,  # type: ignore[arg-type]
            title=node.title,
            description=node.description,
            screenshot_url=screenshot_to_url(session_uuid, node.screenshot_path),
            annotated_screenshot_url=screenshot_to_url(session_uuid, node.annotated_screenshot_path),
            bbox=bbox,
            center=center,
            screen_width=node.screen_width,
            screen_height=node.screen_height,
            screen_fingerprint=node.screen_fingerprint,
            status=node.status,  # type: ignore[arg-type]
            depth=node.depth,
            confidence=node.confidence,
            created_at=node.created_at,
            updated_at=node.updated_at,
        )

    def session_to_response(self, session: MonkeySession) -> MonkeySessionResponse:
        return MonkeySessionResponse(
            session_uuid=session.session_uuid,
            serial=session.serial,
            target_app_name=session.target_app_name,
            status=session.status,  # type: ignore[arg-type]
            llm_provider=session.llm_provider,
            step_count=session.step_count,
            max_steps=session.max_steps,
            max_depth=session.max_depth,
            current_node_uuid=session.current_node_uuid,
            error=session.error,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def tree_to_response(self, session: MonkeySession) -> MonkeyTreeResponse:
        nodes = sorted(session.nodes, key=lambda item: (item.depth, item.id))
        return MonkeyTreeResponse(
            session_uuid=session.session_uuid,
            nodes=[self.node_to_response(session.session_uuid, node) for node in nodes],
        )

    def logs_to_items(self, session: MonkeySession) -> list[MonkeyLogItem]:
        items: list[MonkeyLogItem] = []
        for log in sorted(session.logs, key=lambda item: item.created_at):
            detail = json.loads(log.detail_json) if log.detail_json else None
            items.append(
                MonkeyLogItem(
                    id=log.id,
                    step_index=log.step_index,
                    log_type=log.log_type,
                    message=log.message,
                    detail=detail,
                    created_at=log.created_at,
                )
            )
        return items

    def actions_to_response(self, session: MonkeySession) -> list[MonkeyActionRecordResponse]:
        return [
            MonkeyActionRecordResponse(
                step_index=record.step_index,
                tool_name=record.tool_name,
                node_uuid=record.node_uuid,
                x=record.x,
                y=record.y,
                title=record.title,
                result=record.result,
                created_at=record.created_at,
            )
            for record in sorted(session.actions, key=lambda item: item.step_index)
        ]


def compute_screen_fingerprint(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()[:16]


def decode_data_url(data_url: str) -> bytes:
    payload = data_url.split(",", 1)[-1]
    return base64.b64decode(payload)


monkey_repository = MonkeyRepository()
