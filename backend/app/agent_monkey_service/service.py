from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.explorer import monkey_explorer
from app.agent_monkey_service.repository import monkey_repository
from app.agent_monkey_service.run_registry import monkey_run_registry
from app.agent_monkey_service.schemas import (
    CreateMonkeySessionRequest,
    MonkeySessionResponse,
    MonkeyTreeResponse,
    ProviderInfo,
    ProvidersResponse,
)
from app.agent_test_service.llm_factory import default_provider, probe_providers
from app.services.adb import adb_service


class AgentMonkeyService:
    async def get_providers(self) -> ProvidersResponse:
        specs = await probe_providers()
        infos = [
            ProviderInfo(
                id=spec.id,
                label=spec.label,
                model=spec.model,
                base_url=spec.base_url,
                available=spec.available,
            )
            for spec in specs
        ]
        configured = default_provider()
        resolved = None
        if configured and any(i.available and i.id == configured for i in infos):
            resolved = configured
        else:
            for info in infos:
                if info.available:
                    resolved = info.id
                    break
        return ProvidersResponse(providers=infos, default=resolved)

    async def create_session(
        self, payload: CreateMonkeySessionRequest, db: AsyncSession
    ) -> MonkeySessionResponse:
        serial = payload.serial
        if not serial:
            devices = adb_service.list_devices()
            if devices:
                serial = devices[0].serial
                adb_service.set_active_device(serial)
        provider = payload.llm_provider or default_provider()
        session = await monkey_repository.create_session(
            db,
            serial=serial,
            target_app_name=payload.target_app_name,
            llm_provider=provider,
            max_steps=payload.max_steps,
            max_depth=payload.max_depth,
        )
        return monkey_repository.session_to_response(session)

    async def list_sessions(self, db: AsyncSession, limit: int = 20) -> list[MonkeySessionResponse]:
        sessions = await monkey_repository.list_sessions(db, limit=limit)
        return [monkey_repository.session_to_response(item) for item in sessions]

    async def get_session(self, db: AsyncSession, session_uuid: str) -> MonkeySessionResponse | None:
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            return None
        return monkey_repository.session_to_response(session)

    async def get_tree(self, db: AsyncSession, session_uuid: str) -> MonkeyTreeResponse | None:
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            return None
        return monkey_repository.tree_to_response(session)

    async def stop_session(self, db: AsyncSession, session_uuid: str) -> bool:
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            return False
        monkey_run_registry.request_cancel(session_uuid)
        return True

    async def delete_session(self, db: AsyncSession, session_uuid: str) -> bool:
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            return False
        monkey_run_registry.request_cancel(session_uuid)
        await monkey_repository.delete_session(db, session)
        return True

    async def stream_explore(self, db: AsyncSession, session_uuid: str) -> AsyncGenerator[str, None]:
        async for chunk in monkey_explorer.explore(db, session_uuid):
            yield chunk


agent_monkey_service = AgentMonkeyService()
