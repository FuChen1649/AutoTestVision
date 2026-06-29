from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_code_service.service import agent_test_code_service
from app.agent_test_service.llm_factory import default_provider
from app.agent_test_service.repository import agent_repository
from app.agent_test_service.service import agent_test_service
from app.models.agent import AgentRun, AgentRunStep
from app.models.agent_code import AgentCodeRun, AgentCodeRunStep
from app.models.case import Case, CaseStep
from app.schemas.case import CaseCreate, CaseStepCreate
from app.schemas.case_live import AgentLiveMode, LiveStepExecuteRequest, LiveStepExecuteResponse
from app.services.adb import adb_service


def _metadata_to_json(metadata: dict | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(metadata, ensure_ascii=False)


def _build_case_step(step: CaseStepCreate, index: int) -> CaseStep:
    return CaseStep(
        description=step.description,
        step_order=step.step_order if step.step_order is not None else index,
        step_type=step.step_type or "natural",
        screen_image=step.screen_image,
        screen_width=step.screen_width,
        screen_height=step.screen_height,
        selection_x=step.selection_x,
        selection_y=step.selection_y,
        selection_width=step.selection_width,
        selection_height=step.selection_height,
        metadata_json=_metadata_to_json(step.metadata_json),
    )


async def _upsert_case(db: AsyncSession, payload: LiveStepExecuteRequest) -> Case:
    steps = [CaseStepCreate.model_validate(item) for item in payload.steps]
    if payload.case_id:
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).where(Case.id == payload.case_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            raise RuntimeError("Case 不存在")
        case.name = payload.case_name
        case.script_content = payload.script_content
        case.steps.clear()
        for index, step in enumerate(steps):
            case.steps.append(_build_case_step(step, index))
        await db.flush()
        await db.refresh(case, attribute_names=["steps"])
        return case

    case = Case(name=payload.case_name, script_content=payload.script_content)
    for index, step in enumerate(steps):
        case.steps.append(_build_case_step(step, index))
    db.add(case)
    await db.flush()
    await db.refresh(case, attribute_names=["steps"])
    return case


def _resolve_serial(serial: str | None) -> str:
    target = serial or adb_service.get_active_serial()
    if not target:
        devices = adb_service.list_devices()
        if not devices:
            raise RuntimeError("未连接设备")
        target = devices[0].serial
        adb_service.set_active_device(target)
    return target


def _sync_position_run_steps(run: AgentRun, case: Case) -> None:
    case_steps = sorted(case.steps, key=lambda item: item.step_order)
    existing = {step.step_order: step for step in run.steps}
    for index, case_step in enumerate(case_steps):
        order = case_step.step_order if case_step.step_order is not None else index
        if order in existing:
            run_step = existing[order]
            if run_step.status in {"pending"}:
                run_step.description = case_step.description
                run_step.step_type = case_step.step_type
                run_step.reference_image = case_step.screen_image
                run_step.reference_x = case_step.selection_x
                run_step.reference_y = case_step.selection_y
                run_step.reference_width = case_step.selection_width
                run_step.reference_height = case_step.selection_height
                run_step.metadata_json = case_step.metadata_json
            continue
        run.steps.append(
            AgentRunStep(
                step_order=order,
                step_type=case_step.step_type,
                description=case_step.description,
                status="pending",
                reference_image=case_step.screen_image,
                reference_x=case_step.selection_x,
                reference_y=case_step.selection_y,
                reference_width=case_step.selection_width,
                reference_height=case_step.selection_height,
                metadata_json=case_step.metadata_json,
            )
        )
    run.total_steps = len(case_steps)
    run.case_name = case.name
    if run.status == "completed" and run.current_step_index < run.total_steps:
        run.status = "pending"


def _sync_code_run_steps(run: AgentCodeRun, case: Case) -> None:
    case_steps = sorted(case.steps, key=lambda item: item.step_order)
    existing = {step.step_order: step for step in run.steps}
    for index, case_step in enumerate(case_steps):
        order = case_step.step_order if case_step.step_order is not None else index
        if order in existing:
            run_step = existing[order]
            if run_step.status in {"pending"}:
                run_step.description = case_step.description
                run_step.step_type = case_step.step_type
                run_step.reference_image = case_step.screen_image
                run_step.reference_x = case_step.selection_x
                run_step.reference_y = case_step.selection_y
                run_step.reference_width = case_step.selection_width
                run_step.reference_height = case_step.selection_height
                run_step.metadata_json = case_step.metadata_json
            continue
        run.steps.append(
            AgentCodeRunStep(
                step_order=order,
                step_type=case_step.step_type,
                description=case_step.description,
                status="pending",
                reference_image=case_step.screen_image,
                reference_x=case_step.selection_x,
                reference_y=case_step.selection_y,
                reference_width=case_step.selection_width,
                reference_height=case_step.selection_height,
                metadata_json=case_step.metadata_json,
            )
        )
    run.total_steps = len(case_steps)
    run.case_name = case.name
    run.script_content = case.script_content or ""
    if run.status == "completed" and run.current_step_index < run.total_steps:
        run.status = "pending"


class CaseLiveService:
    async def execute_step(
        self, payload: LiveStepExecuteRequest, db: AsyncSession
    ) -> LiveStepExecuteResponse:
        if payload.commit_step_index >= len(payload.steps):
            raise RuntimeError("commit_step_index 超出步骤范围")

        case = await _upsert_case(db, payload)
        serial = _resolve_serial(payload.serial)
        provider = payload.llm_provider or default_provider()
        mode: AgentLiveMode = payload.agent_mode

        if mode == "position":
            run, finished, message = await self._execute_position_step(
                db, case, payload, serial=serial, provider=provider
            )
            run_dict = agent_repository.to_response(run).model_dump()
        else:
            run, finished, message = await self._execute_code_step(
                db, case, payload, serial=serial, provider=provider
            )
            run_dict = agent_code_repository.to_response(run).model_dump()

        await db.commit()
        await db.refresh(case, attribute_names=["steps"])
        return LiveStepExecuteResponse(
            case=case,
            run_id=run.run_uuid,
            agent_mode=mode,
            run=run_dict,
            finished=finished,
            message=message,
        )

    async def _execute_position_step(
        self,
        db: AsyncSession,
        case: Case,
        payload: LiveStepExecuteRequest,
        *,
        serial: str,
        provider: str | None,
    ) -> tuple[AgentRun, bool, str]:
        run: AgentRun | None = None
        if payload.run_id:
            run = await agent_repository.get_run_by_uuid(db, payload.run_id)
            if not run or run.source_case_id != case.id:
                raise RuntimeError("运行实例与 Case 不匹配")
            _sync_position_run_steps(run, case)
            await agent_repository.update_run_fields(
                db,
                run,
                case_name=case.name,
                total_steps=run.total_steps,
                status=run.status,
            )
            await db.flush()
        else:
            run = await agent_repository.create_run(
                db,
                case,
                serial,
                payload.max_retries,
                llm_provider=provider,
                enable_verifier=payload.enable_verifier,
                auto_commit=False,
            )

        finished = False
        message = "步骤执行完成"
        commit_index = payload.commit_step_index

        while run.current_step_index <= commit_index:
            if run.status in {"failed", "cancelled"}:
                finished = True
                message = f"运行状态：{run.status}"
                break
            if run.status == "completed" and run.current_step_index > commit_index:
                finished = True
                message = "运行已结束"
                break

            result = await agent_test_service.advance_step(run.run_uuid, db)
            run = await agent_repository.get_run_by_uuid(db, run.run_uuid)
            assert run is not None
            finished = result.finished
            message = result.message
            if run.status == "failed":
                break
            if run.current_step_index > commit_index:
                break

        return run, finished, message

    async def _execute_code_step(
        self,
        db: AsyncSession,
        case: Case,
        payload: LiveStepExecuteRequest,
        *,
        serial: str,
        provider: str | None,
    ) -> tuple[AgentCodeRun, bool, str]:
        run: AgentCodeRun | None = None
        if payload.run_id:
            run = await agent_code_repository.get_run_by_uuid(db, payload.run_id)
            if not run or run.source_case_id != case.id:
                raise RuntimeError("运行实例与 Case 不匹配")
            _sync_code_run_steps(run, case)
            await agent_code_repository.update_run_fields(
                db,
                run,
                case_name=case.name,
                total_steps=run.total_steps,
                script_content=case.script_content or "",
                status=run.status,
            )
            await db.flush()
        else:
            run = await agent_code_repository.create_run(
                db,
                case,
                serial,
                payload.max_retries,
                llm_provider=provider,
                enable_verifier=payload.enable_verifier,
                auto_commit=False,
            )

        finished = False
        message = "步骤执行完成"
        commit_index = payload.commit_step_index

        while run.current_step_index <= commit_index:
            if run.status in {"failed", "cancelled"}:
                finished = True
                message = f"运行状态：{run.status}"
                break
            if run.status == "completed" and run.current_step_index > commit_index:
                finished = True
                message = "运行已结束"
                break

            result = await agent_test_code_service.advance_step(run.run_uuid, db)
            run = await agent_code_repository.get_run_by_uuid(db, run.run_uuid)
            assert run is not None
            finished = result.finished
            message = result.message
            if run.status == "failed":
                break
            if run.current_step_index > commit_index:
                break

        return run, finished, message


case_live_service = CaseLiveService()
