from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.case_recording_service.schemas import (
    GeneratedStepDraft,
    RecordingEventResponse,
    RecordingSessionResponse,
)
from app.models.case_recording import CaseRecordingEvent, CaseRecordingLog, CaseRecordingSession

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RECORDING_DATA_ROOT = BACKEND_ROOT / "data" / "case-recording"


def recording_session_dir(session_uuid: str) -> Path:
    path = RECORDING_DATA_ROOT / session_uuid
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_url(session_uuid: str, filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/api/case-recording/sessions/{session_uuid}/assets/{filename}"


class CaseRecordingRepository:
    async def create_session(
        self,
        db: AsyncSession,
        *,
        serial: str | None,
        case_name: str,
        llm_provider: str | None,
    ) -> CaseRecordingSession:
        session = CaseRecordingSession(
            session_uuid=str(uuid.uuid4()),
            serial=serial,
            case_name=case_name.strip() or "录制 Case",
            status="recording",
            llm_provider=llm_provider,
        )
        db.add(session)
        await db.commit()
        session_uuid = session.session_uuid
        recording_session_dir(session_uuid)
        loaded = await self.get_session(db, session_uuid)
        assert loaded is not None
        return loaded

    async def get_session(self, db: AsyncSession, session_uuid: str) -> CaseRecordingSession | None:
        result = await db.execute(
            select(CaseRecordingSession)
            .options(selectinload(CaseRecordingSession.events))
            .where(CaseRecordingSession.session_uuid == session_uuid)
        )
        return result.scalar_one_or_none()

    async def add_event(
        self,
        db: AsyncSession,
        session: CaseRecordingSession,
        *,
        action_type: str,
        x: int | None,
        y: int | None,
        x2: int | None,
        y2: int | None,
        duration_ms: int | None,
        key_name: str | None,
        before_image_filename: str,
        after_image_filename: str,
        before_xml_filename: str,
        after_xml_filename: str,
        device_width: int,
        device_height: int,
        element_hint: str | None,
    ) -> CaseRecordingEvent:
        event = CaseRecordingEvent(
            event_uuid=str(uuid.uuid4()),
            session_id=session.id,
            step_order=session.event_count,
            action_type=action_type,
            x=x,
            y=y,
            x2=x2,
            y2=y2,
            duration_ms=duration_ms,
            key_name=key_name,
            before_image_path=before_image_filename,
            after_image_path=after_image_filename,
            before_xml_path=before_xml_filename,
            after_xml_path=after_xml_filename,
            device_width=device_width,
            device_height=device_height,
            element_hint=element_hint,
        )
        session.event_count += 1
        db.add(event)
        await db.commit()
        await db.refresh(event)
        await db.refresh(session)
        return event

    async def update_session_status(
        self,
        db: AsyncSession,
        session: CaseRecordingSession,
        *,
        status: str,
        generated_steps: list[GeneratedStepDraft] | None = None,
        saved_case_id: int | None = None,
        error: str | None = None,
    ) -> CaseRecordingSession:
        session.status = status
        if generated_steps is not None:
            session.generated_steps_json = json.dumps(
                [step.model_dump() for step in generated_steps], ensure_ascii=False
            )
        if saved_case_id is not None:
            session.saved_case_id = saved_case_id
        if error is not None:
            session.error = error
        session_uuid = session.session_uuid
        await db.commit()
        loaded = await self.get_session(db, session_uuid)
        assert loaded is not None
        return loaded

    async def add_log(
        self,
        db: AsyncSession,
        session: CaseRecordingSession,
        *,
        log_type: str,
        message: str,
        step_order: int | None = None,
        detail: dict | None = None,
    ) -> CaseRecordingLog:
        log = CaseRecordingLog(
            session_id=session.id,
            step_order=step_order,
            log_type=log_type,
            message=message,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    async def list_logs(
        self, db: AsyncSession, session_uuid: str, *, after_id: int = 0
    ) -> tuple[list[CaseRecordingLog], int] | None:
        session = await self.get_session(db, session_uuid)
        if not session:
            return None
        result = await db.execute(
            select(CaseRecordingLog)
            .where(CaseRecordingLog.session_id == session.id, CaseRecordingLog.id > after_id)
            .order_by(CaseRecordingLog.id)
        )
        items = list(result.scalars().all())
        total_result = await db.execute(
            select(CaseRecordingLog).where(CaseRecordingLog.session_id == session.id)
        )
        total = len(total_result.scalars().all())
        return items, total

    def to_log_item(self, log: CaseRecordingLog) -> dict:
        detail = None
        if log.detail_json:
            try:
                detail = json.loads(log.detail_json)
            except json.JSONDecodeError:
                detail = {"raw": log.detail_json}
        return {
            "id": log.id,
            "step_order": log.step_order,
            "log_type": log.log_type,
            "message": log.message,
            "detail": detail,
            "created_at": log.created_at,
        }

    async def delete_session(self, db: AsyncSession, session_uuid: str) -> bool:
        session = await self.get_session(db, session_uuid)
        if not session:
            return False
        await db.delete(session)
        await db.commit()
        session_dir = recording_session_dir(session_uuid)
        if session_dir.exists():
            for child in session_dir.iterdir():
                child.unlink(missing_ok=True)
            session_dir.rmdir()
        return True

    def save_png(self, session_uuid: str, filename: str, image_bytes: bytes) -> str:
        path = recording_session_dir(session_uuid) / filename
        path.write_bytes(image_bytes)
        return filename

    def save_xml(self, session_uuid: str, filename: str, xml: str) -> str:
        path = recording_session_dir(session_uuid) / filename
        path.write_text(xml, encoding="utf-8")
        return filename

    def read_image_data_uri(self, session_uuid: str, filename: str | None) -> str | None:
        if not filename:
            return None
        path = recording_session_dir(session_uuid) / filename
        if not path.exists():
            return None
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def to_session_response(self, session: CaseRecordingSession) -> RecordingSessionResponse:
        generated_steps: list[GeneratedStepDraft] = []
        if session.generated_steps_json:
            try:
                raw = json.loads(session.generated_steps_json)
                generated_steps = [GeneratedStepDraft.model_validate(item) for item in raw]
            except (json.JSONDecodeError, ValueError):
                generated_steps = []

        insp = sa_inspect(session)
        event_rows = [] if "events" in insp.unloaded else list(session.events)
        events = [self._to_event_response(session.session_uuid, event) for event in event_rows]
        return RecordingSessionResponse(
            session_uuid=session.session_uuid,
            serial=session.serial,
            case_name=session.case_name,
            status=session.status,  # type: ignore[arg-type]
            llm_provider=session.llm_provider,
            event_count=session.event_count,
            generated_steps=generated_steps,
            saved_case_id=session.saved_case_id,
            error=session.error,
            events=events,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _to_event_response(self, session_uuid: str, event: CaseRecordingEvent) -> RecordingEventResponse:
        return RecordingEventResponse(
            event_uuid=event.event_uuid,
            step_order=event.step_order,
            action_type=event.action_type,
            x=event.x,
            y=event.y,
            x2=event.x2,
            y2=event.y2,
            duration_ms=event.duration_ms,
            key_name=event.key_name,
            before_image_url=asset_url(session_uuid, event.before_image_path),
            after_image_url=asset_url(session_uuid, event.after_image_path),
            device_width=event.device_width,
            device_height=event.device_height,
            element_hint=event.element_hint,
            created_at=event.created_at,
        )


case_recording_repository = CaseRecordingRepository()
