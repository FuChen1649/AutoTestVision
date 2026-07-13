import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.log_service.schemas import LogEntryResponse, LogListResponse
from app.models.agent import AgentLog, AgentRun
from app.models.agent_code import AgentCodeLog, AgentCodeRun
from app.models.case_recording import CaseRecordingLog, CaseRecordingSession
from app.models.monkey import MonkeyLog, MonkeySession
from app.models.platform_log import PlatformTaskLog
from app.models.task import PlatformTask


class LogService:
    async def _count_position(self, db: AsyncSession, run_uuid: str | None) -> int:
        query = select(func.count()).select_from(AgentLog).join(AgentRun, AgentLog.run_id == AgentRun.id)
        if run_uuid:
            query = query.where(AgentRun.run_uuid == run_uuid)
        return int((await db.execute(query)).scalar() or 0)

    async def _count_code(self, db: AsyncSession, run_uuid: str | None) -> int:
        query = select(func.count()).select_from(AgentCodeLog).join(
            AgentCodeRun, AgentCodeLog.run_id == AgentCodeRun.id
        )
        if run_uuid:
            query = query.where(AgentCodeRun.run_uuid == run_uuid)
        return int((await db.execute(query)).scalar() or 0)

    async def _count_monkey(self, db: AsyncSession, session_uuid: str | None = None) -> int:
        query = select(func.count()).select_from(MonkeyLog)
        if session_uuid:
            query = query.join(MonkeySession, MonkeyLog.session_id == MonkeySession.id).where(
                MonkeySession.session_uuid == session_uuid
            )
        return int((await db.execute(query)).scalar() or 0)

    async def _count_script_gen(self, db: AsyncSession, task_uuid: str | None) -> int:
        query = select(func.count()).select_from(PlatformTaskLog)
        if task_uuid:
            query = query.where(PlatformTaskLog.task_uuid == task_uuid)
        return int((await db.execute(query)).scalar() or 0)

    async def _count_case_recording(self, db: AsyncSession, session_uuid: str | None) -> int:
        query = select(func.count()).select_from(CaseRecordingLog).join(
            CaseRecordingSession, CaseRecordingLog.session_id == CaseRecordingSession.id
        )
        if session_uuid:
            query = query.where(CaseRecordingSession.session_uuid == session_uuid)
        return int((await db.execute(query)).scalar() or 0)

    async def list_logs(
        self,
        db: AsyncSession,
        *,
        source: str | None = None,
        run_uuid: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> LogListResponse:
        items: list[LogEntryResponse] = []
        total = 0

        if source in (None, "position"):
            total += await self._count_position(db, run_uuid)
            query = select(AgentLog, AgentRun.run_uuid).join(AgentRun, AgentLog.run_id == AgentRun.id)
            if run_uuid:
                query = query.where(AgentRun.run_uuid == run_uuid)
            query = query.order_by(AgentLog.created_at.desc()).limit(limit + offset)
            result = await db.execute(query)
            for log, ru in result.all()[offset : offset + limit]:
                detail = self._parse_detail(log.detail_json)
                items.append(
                    LogEntryResponse(
                        id=log.id,
                        source="position",
                        run_uuid=ru,
                        step_order=log.step_order,
                        agent_type=log.agent_type,
                        message=log.message,
                        detail=detail,
                        created_at=log.created_at,
                    )
                )

        if source in (None, "code"):
            total += await self._count_code(db, run_uuid)
            query = select(AgentCodeLog, AgentCodeRun.run_uuid).join(
                AgentCodeRun, AgentCodeLog.run_id == AgentCodeRun.id
            )
            if run_uuid:
                query = query.where(AgentCodeRun.run_uuid == run_uuid)
            query = query.order_by(AgentCodeLog.created_at.desc()).limit(limit + offset)
            result = await db.execute(query)
            for log, ru in result.all()[offset : offset + limit]:
                detail = self._parse_detail(log.detail_json)
                items.append(
                    LogEntryResponse(
                        id=log.id,
                        source="code",
                        run_uuid=ru,
                        step_order=log.step_order,
                        agent_type=log.agent_type,
                        message=log.message,
                        detail=detail,
                        created_at=log.created_at,
                    )
                )

        if source in (None, "monkey"):
            total += await self._count_monkey(db, run_uuid)
            query = (
                select(MonkeyLog, MonkeySession.session_uuid)
                .join(MonkeySession, MonkeyLog.session_id == MonkeySession.id)
                .order_by(MonkeyLog.created_at.desc())
                .limit(limit + offset)
            )
            if run_uuid:
                query = query.where(MonkeySession.session_uuid == run_uuid)
            result = await db.execute(query)
            for log, su in result.all()[offset : offset + limit]:
                detail = self._parse_detail(log.detail_json)
                items.append(
                    LogEntryResponse(
                        id=log.id,
                        source="monkey",
                        session_uuid=su,
                        step_order=log.step_index,
                        agent_type=log.log_type,
                        message=log.message,
                        detail=detail,
                        created_at=log.created_at,
                    )
                )

        if source in (None, "script_gen", "dual"):
            total += await self._count_script_gen(db, run_uuid)
            query = (
                select(PlatformTaskLog, PlatformTask.exec_mode, PlatformTask.case_name)
                .join(PlatformTask, PlatformTask.task_uuid == PlatformTaskLog.task_uuid)
                .order_by(PlatformTaskLog.created_at.desc())
                .limit(limit + offset)
            )
            if run_uuid:
                query = query.where(PlatformTaskLog.task_uuid == run_uuid)
            if source == "script_gen":
                query = query.where(PlatformTask.task_type == "script_generation")
            elif source == "dual":
                query = query.where(PlatformTask.task_type == "script_generation")
            result = await db.execute(query)
            for log, exec_mode, case_name in result.all()[offset : offset + limit]:
                detail = self._parse_detail(log.detail_json) or {}
                detail.setdefault("exec_mode", exec_mode)
                detail.setdefault("case_name", case_name)
                items.append(
                    LogEntryResponse(
                        id=log.id,
                        source="script_gen",
                        run_uuid=log.task_uuid,
                        step_order=log.step_order,
                        agent_type=log.agent_type,
                        message=log.message,
                        detail=detail,
                        created_at=log.created_at,
                    )
                )

        if source in (None, "case_recording", "recording"):
            total += await self._count_case_recording(db, run_uuid)
            query = (
                select(CaseRecordingLog, CaseRecordingSession.session_uuid, CaseRecordingSession.case_name)
                .join(CaseRecordingSession, CaseRecordingLog.session_id == CaseRecordingSession.id)
                .order_by(CaseRecordingLog.created_at.desc())
                .limit(limit + offset)
            )
            if run_uuid:
                query = query.where(CaseRecordingSession.session_uuid == run_uuid)
            result = await db.execute(query)
            for log, session_uuid, case_name in result.all()[offset : offset + limit]:
                detail = self._parse_detail(log.detail_json) or {}
                detail.setdefault("case_name", case_name)
                items.append(
                    LogEntryResponse(
                        id=log.id,
                        source="case_recording",
                        session_uuid=session_uuid,
                        step_order=log.step_order,
                        agent_type=log.log_type,
                        message=log.message,
                        detail=detail,
                        created_at=log.created_at,
                    )
                )

        items.sort(key=lambda entry: entry.created_at, reverse=True)
        page = items[:limit]
        if source:
            total = await self._total_for_source(db, source, run_uuid)
        return LogListResponse(items=page, total=total or len(items))

    async def _total_for_source(self, db: AsyncSession, source: str, run_uuid: str | None) -> int:
        if source == "position":
            return await self._count_position(db, run_uuid)
        if source == "code":
            return await self._count_code(db, run_uuid)
        if source == "monkey":
            return await self._count_monkey(db, run_uuid)
        if source in ("script_gen", "dual"):
            return await self._count_script_gen(db, run_uuid)
        if source in ("case_recording", "recording"):
            return await self._count_case_recording(db, run_uuid)
        return 0

    @staticmethod
    def _parse_detail(raw: str | None) -> dict | None:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}


log_service = LogService()
