from __future__ import annotations

import asyncio
import base64

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_test_service.action_executor import action_executor
from app.agent_test_code_service.ui_dump import dump_ui_xml_async
from app.case_recording_service.recording_annotation import display_image_filename
from app.case_recording_service.repository import case_recording_repository
from app.case_recording_service.schemas import (
    ConfirmRecordingRequest,
    ConfirmRecordingResponse,
    CreateRecordingSessionRequest,
    GeneratedStepDraft,
    ProvidersResponse,
    RecordActionRequest,
    RecordingLogItem,
    RecordingLogsResponse,
    RecordingSessionResponse,
)
from app.case_recording_service.step_generator import recording_step_generator
from app.models.case import Case, CaseStep
from app.services.adb import adb_service
from app.agent_test_service.llm_factory import list_providers as llm_list_providers, probe_providers


class CaseRecordingService:
    async def get_providers(self) -> ProvidersResponse:
        specs = await probe_providers()
        if not specs:
            specs = llm_list_providers()
        return ProvidersResponse(
            providers=[
                {"id": spec.id, "label": spec.label, "available": spec.available}
                for spec in specs
            ]
        )

    async def create_session(
        self, payload: CreateRecordingSessionRequest, db: AsyncSession
    ) -> RecordingSessionResponse:
        session = await case_recording_repository.create_session(
            db,
            serial=payload.serial,
            case_name=payload.case_name,
            llm_provider=payload.llm_provider,
        )
        await case_recording_repository.add_log(
            db,
            session,
            log_type="session",
            message="录制会话已创建",
            detail={
                "serial": payload.serial,
                "case_name": session.case_name,
                "llm_provider": payload.llm_provider,
            },
        )
        return case_recording_repository.to_session_response(session)

    async def get_session(self, db: AsyncSession, session_uuid: str) -> RecordingSessionResponse | None:
        session = await case_recording_repository.get_session(db, session_uuid)
        if not session:
            return None
        return case_recording_repository.to_session_response(session)

    async def record_action(
        self, db: AsyncSession, session_uuid: str, payload: RecordActionRequest
    ) -> RecordingSessionResponse:
        session = await case_recording_repository.get_session(db, session_uuid)
        if not session:
            raise ValueError("会话不存在")
        if session.status != "recording":
            raise ValueError("会话未处于录制状态")

        serial = session.serial
        order = session.event_count
        prefix = f"event_{order:04d}"

        before_image, width, height = await action_executor.capture_screen(serial)
        before_xml = await dump_ui_xml_async(serial)
        before_bytes = self._decode_data_uri(before_image)
        case_recording_repository.save_png(session.session_uuid, f"{prefix}_before.png", before_bytes)
        case_recording_repository.save_xml(session.session_uuid, f"{prefix}_before.xml", before_xml)

        await self._execute_action(payload, serial)

        after_image, _, _ = await action_executor.capture_after_screen(serial)
        after_xml = await dump_ui_xml_async(serial)
        after_bytes = self._decode_data_uri(after_image)
        case_recording_repository.save_png(session.session_uuid, f"{prefix}_after.png", after_bytes)
        case_recording_repository.save_xml(session.session_uuid, f"{prefix}_after.xml", after_xml)

        await case_recording_repository.add_event(
            db,
            session,
            action_type=payload.action_type,
            x=payload.x,
            y=payload.y,
            x2=payload.x2,
            y2=payload.y2,
            duration_ms=payload.duration_ms if payload.action_type != "key" else None,
            key_name=payload.key,
            before_image_filename=f"{prefix}_before.png",
            after_image_filename=f"{prefix}_after.png",
            before_xml_filename=f"{prefix}_before.xml",
            after_xml_filename=f"{prefix}_after.xml",
            device_width=width,
            device_height=height,
            element_hint=None,
        )

        await case_recording_repository.add_log(
            db,
            session,
            log_type="capture",
            step_order=order,
            message=f"已录制步骤 {order + 1}: {payload.action_type}",
            detail={
                "action_type": payload.action_type,
                "x": payload.x,
                "y": payload.y,
                "x2": payload.x2,
                "y2": payload.y2,
                "key": payload.key,
                "device_width": width,
                "device_height": height,
                "before_image": f"{prefix}_before.png",
                "after_image": f"{prefix}_after.png",
            },
        )

        refreshed = await case_recording_repository.get_session(db, session_uuid)
        assert refreshed is not None
        return case_recording_repository.to_session_response(refreshed)

    async def stop_recording(self, db: AsyncSession, session_uuid: str) -> RecordingSessionResponse:
        session = await case_recording_repository.get_session(db, session_uuid)
        if not session:
            raise ValueError("会话不存在")
        if session.status not in ("recording", "failed"):
            return case_recording_repository.to_session_response(session)

        await case_recording_repository.update_session_status(db, session, status="generating", error=None)
        refreshed = await case_recording_repository.get_session(db, session_uuid)
        assert refreshed is not None
        try:
            steps = await recording_step_generator.generate(
                db, refreshed, list(refreshed.events), provider=refreshed.llm_provider
            )
            await case_recording_repository.update_session_status(
                db, refreshed, status="review", generated_steps=steps, error=None
            )
        except Exception as exc:
            await case_recording_repository.add_log(
                db,
                refreshed,
                log_type="error",
                message="步骤生成失败",
                detail={"error": str(exc)},
            )
            await case_recording_repository.update_session_status(
                db, refreshed, status="failed", error=str(exc)
            )

        refreshed = await case_recording_repository.get_session(db, session_uuid)
        assert refreshed is not None
        return case_recording_repository.to_session_response(refreshed)

    async def confirm_save(
        self, db: AsyncSession, session_uuid: str, payload: ConfirmRecordingRequest
    ) -> ConfirmRecordingResponse:
        session = await case_recording_repository.get_session(db, session_uuid)
        if not session:
            raise ValueError("会话不存在")
        if session.status not in ("review", "generating", "recording"):
            raise ValueError("当前会话不可保存")

        steps = payload.steps
        if steps is None and session.generated_steps_json:
            response = case_recording_repository.to_session_response(session)
            steps = response.generated_steps
        if not steps:
            raise ValueError("没有可保存的步骤")

        case_name = (payload.case_name or session.case_name or "录制 Case").strip()
        case = Case(name=case_name, script_content="")
        events_by_uuid = {event.event_uuid: event for event in session.events}

        for index, step in enumerate(steps):
            event = events_by_uuid.get(step.event_uuid)
            screen_image = None
            if event:
                display_name = display_image_filename(event.step_order)
                display_path = case_recording_repository.read_image_data_uri(
                    session.session_uuid, display_name
                )
                if display_path:
                    screen_image = display_path
                elif event.before_image_path:
                    screen_image = case_recording_repository.read_image_data_uri(
                        session.session_uuid, event.before_image_path
                    )
            case.steps.append(
                CaseStep(
                    description=step.description.strip(),
                    step_order=index,
                    step_type="natural",
                    screen_image=screen_image,
                    screen_width=step.screen_width or (event.device_width if event else None),
                    screen_height=step.screen_height or (event.device_height if event else None),
                    selection_x=step.selection_x,
                    selection_y=step.selection_y,
                    selection_width=step.selection_width,
                    selection_height=step.selection_height,
                )
            )

        db.add(case)
        await db.commit()
        await db.refresh(case, attribute_names=["steps"])

        await case_recording_repository.update_session_status(
            db, session, status="saved", saved_case_id=case.id, error=None
        )

        return ConfirmRecordingResponse(case_id=case.id, case_name=case.name, step_count=len(case.steps))

    async def cancel_session(self, db: AsyncSession, session_uuid: str) -> bool:
        session = await case_recording_repository.get_session(db, session_uuid)
        if not session:
            return False
        await case_recording_repository.update_session_status(db, session, status="cancelled")
        return True

    async def delete_session(self, db: AsyncSession, session_uuid: str) -> bool:
        return await case_recording_repository.delete_session(db, session_uuid)

    async def get_logs(
        self, db: AsyncSession, session_uuid: str, *, after_id: int = 0
    ) -> RecordingLogsResponse | None:
        result = await case_recording_repository.list_logs(db, session_uuid, after_id=after_id)
        if result is None:
            return None
        items, total = result
        return RecordingLogsResponse(
            items=[RecordingLogItem.model_validate(case_recording_repository.to_log_item(log)) for log in items],
            total=total,
        )

    async def _execute_action(self, payload: RecordActionRequest, serial: str | None) -> None:
        if payload.action_type == "tap":
            if payload.x is None or payload.y is None:
                raise ValueError("点击坐标缺失")
            await adb_service.tap(payload.x, payload.y, serial=serial)
        elif payload.action_type == "long_press":
            if payload.x is None or payload.y is None:
                raise ValueError("长按坐标缺失")
            await adb_service.long_press(
                payload.x, payload.y, duration_ms=payload.duration_ms, serial=serial
            )
        elif payload.action_type == "swipe":
            if None in (payload.x, payload.y, payload.x2, payload.y2):
                raise ValueError("滑动坐标缺失")
            await adb_service.swipe(
                payload.x,
                payload.y,
                payload.x2,
                payload.y2,
                duration_ms=payload.duration_ms,
                serial=serial,
            )
        elif payload.action_type == "key":
            if not payload.key:
                raise ValueError("系统键缺失")
            if payload.key == "back":
                await asyncio.to_thread(adb_service.press_back_key, serial)
            elif payload.key == "home":
                await asyncio.to_thread(adb_service.press_home_key, serial)
            else:
                await asyncio.to_thread(adb_service.press_recents_key, serial)
        else:
            raise ValueError(f"不支持的操作: {payload.action_type}")

    def _decode_data_uri(self, data_uri: str) -> bytes:
        if "," in data_uri:
            encoded = data_uri.split(",", 1)[1]
        else:
            encoded = data_uri
        return base64.b64decode(encoded)


case_recording_service = CaseRecordingService()
