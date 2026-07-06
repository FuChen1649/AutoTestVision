import json

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.log_service.schemas import LogEntryResponse, LogListResponse
from app.models.agent import AgentLog, AgentRun
from app.models.agent_code import AgentCodeLog, AgentCodeRun
from app.models.monkey import MonkeyLog, MonkeySession


class LogService:
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

        if source in (None, "position"):
            query = select(AgentLog, AgentRun.run_uuid).join(AgentRun, AgentLog.run_id == AgentRun.id)
            if run_uuid:
                query = query.where(AgentRun.run_uuid == run_uuid)
            query = query.order_by(AgentLog.created_at.desc()).limit(limit + offset)
            result = await db.execute(query)
            for log, ru in result.all()[offset : offset + limit]:
                detail = None
                if log.detail_json:
                    try:
                        detail = json.loads(log.detail_json)
                    except json.JSONDecodeError:
                        detail = {"raw": log.detail_json}
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
            query = select(AgentCodeLog, AgentCodeRun.run_uuid).join(
                AgentCodeRun, AgentCodeLog.run_id == AgentCodeRun.id
            )
            if run_uuid:
                query = query.where(AgentCodeRun.run_uuid == run_uuid)
            query = query.order_by(AgentCodeLog.created_at.desc()).limit(limit + offset)
            result = await db.execute(query)
            for log, ru in result.all()[offset : offset + limit]:
                detail = None
                if log.detail_json:
                    try:
                        detail = json.loads(log.detail_json)
                    except json.JSONDecodeError:
                        detail = {"raw": log.detail_json}
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
            query = select(MonkeyLog, MonkeySession.session_uuid).join(
                MonkeySession, MonkeyLog.session_id == MonkeySession.id
            )
            query = query.order_by(MonkeyLog.created_at.desc()).limit(limit + offset)
            result = await db.execute(query)
            for log, su in result.all()[offset : offset + limit]:
                detail = None
                if log.detail_json:
                    try:
                        detail = json.loads(log.detail_json)
                    except json.JSONDecodeError:
                        detail = {"raw": log.detail_json}
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

        items.sort(key=lambda x: x.created_at, reverse=True)
        page = items[:limit]
        return LogListResponse(items=page, total=len(items))


log_service = LogService()
