import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_code_service.code_executor import code_executor
from app.agent_test_code_service.code_generator import code_generator, render_step_test_file
from app.agent_test_code_service.schemas import AnalyzeCodeRequest, GeneratedStepCode
from app.agent_test_code_service.ui_dump import dump_ui_xml_async
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.action_executor import action_executor
from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.intent_analyzer import intent_analyzer
from app.agent_test_service.schemas import ActionIntent, AnalyzeIntentRequest
from app.agent_test_service.tap_resolver import refine_tap_intent
from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_service.repository import agent_repository
from app.database import async_session
from app.models.agent import AgentRun
from app.models.agent_code import AgentCodeRun
from app.models.case import Case, CaseStep
from app.agent_test_service.tools import agent_tools, is_tool_step
from app.platform_service.task_log import append_platform_task_log
from app.platform_service.task_service import register_platform_task, sync_task_status
from app.script_generation_service.registry import ScriptGenRuntime, script_gen_registry
from app.services.adb import adb_service

logger = get_agent_logger()


class GenerateScriptsRequest(BaseModel):
    position_serial: str | None = None
    code_serial: str | None = None
    llm_provider: str | None = None


class ScriptGenPrerequisitesResponse(BaseModel):
    ready: bool
    min_devices: int = 2
    device_count: int
    devices: list[dict] = Field(default_factory=list)
    position_serial: str | None = None
    code_serial: str | None = None
    message: str = ""


class GenerateScriptsResponse(BaseModel):
    task_uuid: str
    case_id: int
    status: str


class DualScriptStepView(BaseModel):
    step_order: int
    step_type: str
    description: str
    script_status: str | None = None
    position_script: ActionIntent | None = None
    code_script: GeneratedStepCode | None = None
    script_generated_at: datetime | None = None


class CaseScriptsResponse(BaseModel):
    case_id: int
    case_name: str
    script_status: str | None = None
    steps: list[DualScriptStepView] = Field(default_factory=list)


class ScriptGenStreamEvent(BaseModel):
    event: str
    task_uuid: str
    case_id: int
    step_order: int | None = None
    message: str = ""
    detail: dict | None = None


class ScriptGenerationService:
    MIN_DEVICES = 2
    _streams: dict[str, asyncio.Queue[ScriptGenStreamEvent | None]] = {}

    def _list_connected_devices(self) -> list:
        return [d for d in adb_service.list_devices() if getattr(d, "connected", True)]

    def _resolve_dual_devices(
        self,
        position_serial: str | None = None,
        code_serial: str | None = None,
    ) -> tuple[str, str, list]:
        devices = self._list_connected_devices()
        if len(devices) < self.MIN_DEVICES:
            raise RuntimeError(
                f"双脚本生成需要至少 {self.MIN_DEVICES} 台已连接设备，当前仅 {len(devices)} 台"
            )

        serials = [d.serial for d in devices]
        pos = position_serial or serials[0]
        code = code_serial or (serials[1] if serials[1] != pos else next(s for s in serials if s != pos))

        if pos not in serials:
            raise RuntimeError(f"Position 设备 {pos} 未连接")
        if code not in serials:
            raise RuntimeError(f"Code 设备 {code} 未连接")
        if pos == code:
            raise RuntimeError("Position 与 Code 必须使用两台不同的设备")

        return pos, code, devices

    def get_prerequisites(
        self,
        position_serial: str | None = None,
        code_serial: str | None = None,
    ) -> ScriptGenPrerequisitesResponse:
        devices = self._list_connected_devices()
        device_payload = [
            {
                "serial": d.serial,
                "model": getattr(d, "model", "") or "",
                "connected": getattr(d, "connected", True),
            }
            for d in devices
        ]
        count = len(devices)
        if count < self.MIN_DEVICES:
            return ScriptGenPrerequisitesResponse(
                ready=False,
                device_count=count,
                devices=device_payload,
                message=f"双脚本生成需要至少 {self.MIN_DEVICES} 台设备，当前 {count} 台",
            )

        try:
            pos, code, _ = self._resolve_dual_devices(position_serial, code_serial)
            return ScriptGenPrerequisitesResponse(
                ready=True,
                device_count=count,
                devices=device_payload,
                position_serial=pos,
                code_serial=code,
                message=f"已就绪：Position={pos}，Code={code}",
            )
        except RuntimeError as exc:
            return ScriptGenPrerequisitesResponse(
                ready=False,
                device_count=count,
                devices=device_payload,
                message=str(exc),
            )

    async def _emit(self, task_uuid: str, event: str, case_id: int, **kwargs) -> None:
        message = kwargs.get("message", "")
        payload = ScriptGenStreamEvent(
            event=event,
            task_uuid=task_uuid,
            case_id=case_id,
            step_order=kwargs.get("step_order"),
            message=message,
            detail=kwargs.get("detail"),
        )
        queue = self._streams.get(task_uuid)
        if queue:
            queue.put_nowait(payload)

        try:
            async with async_session() as db:
                detail = {"event": event, "case_id": case_id}
                if kwargs.get("detail"):
                    detail["payload"] = kwargs["detail"]
                await append_platform_task_log(
                    db,
                    task_uuid,
                    message or event,
                    step_order=kwargs.get("step_order"),
                    agent_type=event,
                    detail=detail,
                    commit=True,
                )
        except Exception as exc:
            logger.warning("[script_gen] 写入平台日志失败: %s", exc)

    async def _init_dual_runs(
        self,
        db: AsyncSession,
        case: Case,
        *,
        position_serial: str,
        code_serial: str,
        llm_provider: str | None,
    ) -> tuple[AgentRun, AgentCodeRun]:
        pos_run = await agent_repository.create_run(
            db,
            case,
            position_serial,
            max_retries=0,
            llm_provider=llm_provider,
            auto_commit=False,
        )
        code_run = await agent_code_repository.create_run(
            db,
            case,
            code_serial,
            max_retries=0,
            llm_provider=llm_provider,
            auto_commit=False,
        )
        pos_run.status = "running"
        code_run.status = "running"
        await db.flush()
        return pos_run, code_run

    async def _persist_position_step(
        self,
        db: AsyncSession,
        pos_run: AgentRun,
        *,
        step_order: int,
        before_image: str,
        before_annotated: str | None,
        after_image: str,
        intent: ActionIntent,
        exec_error: str | None,
    ) -> None:
        status = "failed" if exec_error else "success"
        await agent_repository.update_step(
            db,
            pos_run,
            step_order,
            before_image=before_image,
            before_image_annotated=before_annotated,
            after_image=after_image,
            intent=intent,
            status=status,
            error=exec_error,
        )
        attempt = await agent_repository.create_attempt(
            db, pos_run, step_order, before_annotated or before_image
        )
        await agent_repository.update_latest_attempt(
            db,
            pos_run,
            step_order,
            before_image_annotated=before_annotated,
            after_image=after_image,
            status=status,
            error=exec_error,
        )
        await agent_repository.add_log(
            db,
            pos_run,
            "executor",
            f"步骤 {step_order + 1} Position 执行{'失败' if exec_error else '完成'}",
            step_order=step_order,
            detail={"error": exec_error} if exec_error else None,
        )
        _ = attempt

    async def _persist_code_step(
        self,
        db: AsyncSession,
        code_run: AgentCodeRun,
        *,
        step_order: int,
        before_image: str,
        after_image: str,
        generated: GeneratedStepCode,
        exec_error: str | None,
        ui_xml: str | None = None,
    ) -> None:
        from app.agent_test_code_service.code_annotation import annotate_code_before_image
        from app.agent_test_service.action_executor import action_executor

        status = "failed" if exec_error else "success"
        code_step = next(item for item in code_run.steps if item.step_order == step_order)
        code_step.before_image = before_image
        code_step.after_image = after_image
        code_step.generated_code_json = generated.model_dump_json()
        code_step.template_path = generated.template_path
        code_step.execution_output = generated.execution_output
        code_step.status = status
        code_step.error = exec_error
        if ui_xml:
            code_step.ui_xml = ui_xml
        if before_image and generated.code_line:
            device_w, device_h = await action_executor.get_device_screen_size(code_run.serial)
            annotated = await annotate_code_before_image(
                before_image,
                generated.code_line,
                ui_xml=ui_xml,
                device_width=device_w,
                device_height=device_h,
                serial=code_run.serial,
            )
            if annotated:
                code_step.before_image_annotated = annotated
        await db.flush()
        await agent_code_repository.add_log(
            db,
            code_run,
            "executor",
            f"步骤 {step_order + 1} Code 执行{'失败' if exec_error else '完成'}",
            step_order=step_order,
            detail={"error": exec_error, "code_line": generated.code_line} if exec_error else {"code_line": generated.code_line},
        )

    async def _get_case_step(self, db: AsyncSession, case_id: int, step_order: int) -> CaseStep:
        result = await db.execute(
            select(CaseStep).where(CaseStep.case_id == case_id, CaseStep.step_order == step_order)
        )
        step = result.scalar_one_or_none()
        if not step:
            raise RuntimeError(f"Case 步骤 {step_order} 不存在")
        return step

    async def _sync_step_script_status(
        self, db: AsyncSession, case_id: int, step_order: int, *, failed: bool = False
    ) -> None:
        step = await self._get_case_step(db, case_id, step_order)
        if failed:
            step.script_status = "failed"
        elif step.position_script_json and step.code_script_json:
            step.script_status = "ready"
            if not step.script_generated_at:
                step.script_generated_at = datetime.now(timezone.utc)
        await db.commit()

    async def _run_position_pipeline(
        self,
        *,
        task_uuid: str,
        case_id: int,
        run_uuid: str,
        serial: str,
        llm_provider: str | None,
        total: int,
        runtime: ScriptGenRuntime | None,
    ) -> bool:
        failed = False
        async with async_session() as db:
            case = await self._load_case(db, case_id)
            natural_steps = [s for s in case.steps if not is_tool_step(s.step_type)]
            pos_run = await agent_repository.get_run_by_uuid(db, run_uuid)
            assert pos_run is not None

            for index, step in enumerate(natural_steps):
                if runtime and runtime.cancelled:
                    await sync_task_status(db, task_uuid, status="cancelled", commit=True)
                    await self._emit(task_uuid, "cancelled", case_id, message="Position 路径已取消")
                    return failed

                step_row = await self._get_case_step(db, case_id, step.step_order)
                step_row.script_status = "generating"
                await db.commit()

                await self._emit(
                    task_uuid,
                    "position_step_start",
                    case_id,
                    step_order=step.step_order,
                    message=step.description[:120] or f"Position 步骤 {step.step_order + 1}",
                    detail={"description": step.description, "serial": serial},
                )

                try:
                    pos_image, pos_w, pos_h = await action_executor.capture_screen(serial)
                    await self._emit(
                        task_uuid,
                        "position_capture",
                        case_id,
                        step_order=step.step_order,
                        message="Position 已截取执行前屏幕",
                        detail={
                            "serial": serial,
                            "before_image": pos_image,
                            "width": pos_w,
                            "height": pos_h,
                        },
                    )

                    intent_request = AnalyzeIntentRequest(
                        step_description=step.description,
                        screen_image=pos_image,
                        screen_width=pos_w,
                        screen_height=pos_h,
                        llm_provider=llm_provider,
                    )
                    intent = await intent_analyzer.analyze(intent_request, provider=llm_provider)
                    refined_intent = await refine_tap_intent(
                        intent,
                        step_description=step.description,
                        serial=serial,
                        screen_height=pos_h,
                        screen_width=pos_w,
                    )

                    step_row = await self._get_case_step(db, case_id, step.step_order)
                    step_row.position_script_json = refined_intent.model_dump_json()
                    await db.commit()

                    pos_before_annotated = annotate_before_image(pos_image, refined_intent)
                    await self._emit(
                        task_uuid,
                        "position_script_ready",
                        case_id,
                        step_order=step.step_order,
                        message="Position 脚本已生成",
                        detail={
                            "serial": serial,
                            "before_image": pos_image,
                            "before_image_annotated": pos_before_annotated,
                            "script": refined_intent.model_dump(),
                        },
                    )

                    await self._emit(
                        task_uuid,
                        "position_executing",
                        case_id,
                        step_order=step.step_order,
                        message=f"Position 设备执行 {serial}",
                        detail={"serial": serial},
                    )

                    pos_after = pos_image
                    pos_exec_error: str | None = None
                    if refined_intent.action != "skip":
                        try:
                            pos_dw, pos_dh = await action_executor.get_device_screen_size(serial)
                            mapped = action_executor.map_coordinates(
                                refined_intent,
                                image_width=pos_w,
                                image_height=pos_h,
                                device_width=pos_dw,
                                device_height=pos_dh,
                            )
                            await action_executor.execute(mapped, serial=serial)
                            pos_after, _, _ = await action_executor.capture_after_screen(serial)
                        except Exception as exc:
                            pos_exec_error = str(exc)[-400:]
                            logger.warning(
                                "[script_gen] Position 设备执行失败 step=%d serial=%s: %s",
                                step.step_order,
                                serial,
                                exc,
                            )

                    pos_run = await agent_repository.get_run_by_uuid(db, run_uuid)
                    assert pos_run is not None
                    await self._persist_position_step(
                        db,
                        pos_run,
                        step_order=step.step_order,
                        before_image=pos_image,
                        before_annotated=pos_before_annotated,
                        after_image=pos_after,
                        intent=refined_intent,
                        exec_error=pos_exec_error,
                    )
                    await agent_repository.update_run_fields(
                        db, pos_run, current_step_index=step.step_order + 1
                    )
                    await self._sync_step_script_status(
                        db, case_id, step.step_order, failed=bool(pos_exec_error)
                    )

                    await self._emit(
                        task_uuid,
                        "position_executed",
                        case_id,
                        step_order=step.step_order,
                        message=(
                            f"Position 步骤 {step.step_order + 1} 完成"
                            if not pos_exec_error
                            else f"Position 步骤 {step.step_order + 1} 执行失败"
                        ),
                        detail={
                            "serial": serial,
                            "after_image": pos_after,
                            "exec_error": pos_exec_error,
                        },
                    )
                    if pos_exec_error:
                        failed = True
                except Exception as exc:
                    failed = True
                    step_row = await self._get_case_step(db, case_id, step.step_order)
                    step_row.script_status = "failed"
                    await db.commit()
                    await self._emit(
                        task_uuid,
                        "position_error",
                        case_id,
                        step_order=step.step_order,
                        message=str(exc),
                    )
                    return failed

                await sync_task_status(
                    db,
                    task_uuid,
                    progress={
                        "position_completed_steps": index + 1,
                        "total_steps": total,
                        "message": f"Position 已完成 {index + 1}/{total} 步",
                    },
                    commit=True,
                )
        return failed

    async def _run_code_pipeline(
        self,
        *,
        task_uuid: str,
        case_id: int,
        run_uuid: str,
        serial: str,
        llm_provider: str | None,
        total: int,
        runtime: ScriptGenRuntime | None,
    ) -> bool:
        failed = False
        async with async_session() as db:
            case = await self._load_case(db, case_id)
            natural_steps = [s for s in case.steps if not is_tool_step(s.step_type)]
            code_run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
            assert code_run is not None

            for index, step in enumerate(natural_steps):
                if runtime and runtime.cancelled:
                    await sync_task_status(db, task_uuid, status="cancelled", commit=True)
                    await self._emit(task_uuid, "cancelled", case_id, message="Code 路径已取消")
                    return failed

                step_row = await self._get_case_step(db, case_id, step.step_order)
                if step_row.script_status != "failed":
                    step_row.script_status = "generating"
                await db.commit()

                await self._emit(
                    task_uuid,
                    "code_step_start",
                    case_id,
                    step_order=step.step_order,
                    message=step.description[:120] or f"Code 步骤 {step.step_order + 1}",
                    detail={"description": step.description, "serial": serial},
                )

                try:
                    code_image, code_w, code_h = await action_executor.capture_screen(serial)
                    ui_xml = await dump_ui_xml_async(serial)
                    await self._emit(
                        task_uuid,
                        "code_capture",
                        case_id,
                        step_order=step.step_order,
                        message="Code 已截取执行前屏幕",
                        detail={
                            "serial": serial,
                            "before_image": code_image,
                            "width": code_w,
                            "height": code_h,
                        },
                    )

                    code_request = AnalyzeCodeRequest(
                        step_description=step.description,
                        screen_image=code_image,
                        screen_width=code_w,
                        screen_height=code_h,
                        ui_xml=ui_xml,
                        llm_provider=llm_provider,
                    )
                    generated = await code_generator.analyze(code_request, provider=llm_provider)
                    generated.template_path = str(
                        render_step_test_file(
                            run_uuid=task_uuid,
                            step_order=step.step_order,
                            description=step.description,
                            serial=serial,
                            code_line=generated.code_line,
                        )
                    )

                    step_row = await self._get_case_step(db, case_id, step.step_order)
                    step_row.code_script_json = generated.model_dump_json()
                    await db.commit()

                    await self._emit(
                        task_uuid,
                        "code_script_ready",
                        case_id,
                        step_order=step.step_order,
                        message="Code 脚本已生成",
                        detail={
                            "serial": serial,
                            "before_image": code_image,
                            "script": generated.model_dump(),
                        },
                    )

                    await self._emit(
                        task_uuid,
                        "code_executing",
                        case_id,
                        step_order=step.step_order,
                        message=f"Code 设备执行 {serial}",
                        detail={"serial": serial},
                    )

                    code_after = code_image
                    code_exec_error: str | None = None
                    line = (generated.code_line or "").strip()
                    if line and line != "d.sleep(0.5)":
                        try:
                            exec_result = await code_executor.execute(
                                line,
                                serial=serial,
                                test_file=None,
                            )
                            generated.execution_output = exec_result.execution_output
                            generated.pytest_exit_code = exec_result.pytest_exit_code
                            generated.confidence = exec_result.confidence
                            generated.reasoning = exec_result.reasoning
                            if exec_result.pytest_exit_code not in (None, 0):
                                code_exec_error = (exec_result.execution_output or "Code 执行失败")[-400:]
                            else:
                                code_after, _, _ = await action_executor.capture_after_screen(serial)
                        except Exception as exc:
                            code_exec_error = str(exc)[-400:]
                            logger.warning(
                                "[script_gen] Code 设备执行异常 step=%d serial=%s: %s",
                                step.step_order,
                                serial,
                                exc,
                            )

                    code_run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
                    assert code_run is not None
                    await self._persist_code_step(
                        db,
                        code_run,
                        step_order=step.step_order,
                        before_image=code_image,
                        after_image=code_after,
                        generated=generated,
                        exec_error=code_exec_error,
                        ui_xml=ui_xml,
                    )
                    await agent_code_repository.update_run_fields(
                        db, code_run, current_step_index=step.step_order + 1
                    )
                    await self._sync_step_script_status(
                        db, case_id, step.step_order, failed=bool(code_exec_error)
                    )

                    await self._emit(
                        task_uuid,
                        "code_executed",
                        case_id,
                        step_order=step.step_order,
                        message=(
                            f"Code 步骤 {step.step_order + 1} 完成"
                            if not code_exec_error
                            else f"Code 步骤 {step.step_order + 1} 执行失败"
                        ),
                        detail={
                            "serial": serial,
                            "after_image": code_after,
                            "exec_error": code_exec_error,
                            "script": generated.model_dump(),
                        },
                    )
                    if code_exec_error:
                        failed = True
                except Exception as exc:
                    failed = True
                    step_row = await self._get_case_step(db, case_id, step.step_order)
                    step_row.script_status = "failed"
                    await db.commit()
                    await self._emit(
                        task_uuid,
                        "code_error",
                        case_id,
                        step_order=step.step_order,
                        message=str(exc),
                    )
                    return failed

                await sync_task_status(
                    db,
                    task_uuid,
                    progress={
                        "code_completed_steps": index + 1,
                        "total_steps": total,
                        "message": f"Code 已完成 {index + 1}/{total} 步",
                    },
                    commit=True,
                )
        return failed

    async def _finalize_dual_runs(
        self,
        db: AsyncSession,
        pos_run: AgentRun,
        code_run: AgentCodeRun,
        *,
        completed_steps: int,
        failed: bool,
    ) -> None:
        status = "failed" if failed else "completed"
        await agent_repository.update_run_fields(
            db,
            pos_run,
            status=status,
            current_step_index=completed_steps,
        )
        await agent_code_repository.update_run_fields(
            db,
            code_run,
            status=status,
            current_step_index=completed_steps,
        )

    async def get_case_scripts(self, db: AsyncSession, case_id: int) -> CaseScriptsResponse:
        case = await self._load_case(db, case_id)
        steps: list[DualScriptStepView] = []
        for step in case.steps:
            position = None
            code = None
            if step.position_script_json:
                position = ActionIntent.model_validate_json(step.position_script_json)
            if step.code_script_json:
                code = GeneratedStepCode.model_validate_json(step.code_script_json)
            steps.append(
                DualScriptStepView(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    script_status=step.script_status,
                    position_script=position,
                    code_script=code,
                    script_generated_at=step.script_generated_at,
                )
            )
        statuses = [s.script_status for s in case.steps if s.script_status]
        agg = None
        if statuses:
            if any(s == "failed" for s in statuses):
                agg = "failed"
            elif any(s == "generating" for s in statuses):
                agg = "generating"
            elif all(s == "ready" for s in statuses):
                agg = "ready"
            else:
                agg = statuses[-1]
        return CaseScriptsResponse(case_id=case.id, case_name=case.name, script_status=agg, steps=steps)

    async def start_generation(
        self, db: AsyncSession, case_id: int, payload: GenerateScriptsRequest
    ) -> GenerateScriptsResponse:
        case = await self._load_case(db, case_id)
        position_serial, code_serial, _ = self._resolve_dual_devices(
            payload.position_serial,
            payload.code_serial,
        )

        task = await register_platform_task(
            db,
            task_type="script_generation",
            exec_mode="dual",
            source_case_id=case.id,
            case_name=case.name,
            serial=f"{position_serial},{code_serial}",
            status="running",
            progress={
                "completed_steps": 0,
                "total_steps": len(case.steps),
                "message": f"准备生成（Position={position_serial}, Code={code_serial}）",
            },
            commit=True,
        )

        queue: asyncio.Queue[ScriptGenStreamEvent | None] = asyncio.Queue()
        self._streams[task.task_uuid] = queue
        runtime = script_gen_registry.register(task.task_uuid)

        async def runner() -> None:
            try:
                await self._run_generation(
                    task.task_uuid,
                    case_id,
                    position_serial,
                    code_serial,
                    payload.llm_provider,
                )
            finally:
                queue.put_nowait(None)
                script_gen_registry.remove(task.task_uuid)
                self._streams.pop(task.task_uuid, None)

        runtime.harness_task = asyncio.create_task(runner())
        await self._emit(
            task.task_uuid,
            "started",
            case_id,
            message=f"双设备绑定 Position={position_serial} Code={code_serial}",
            detail={
                "position_serial": position_serial,
                "code_serial": code_serial,
            },
        )
        return GenerateScriptsResponse(task_uuid=task.task_uuid, case_id=case_id, status="running")

    async def stream(self, task_uuid: str) -> AsyncGenerator[ScriptGenStreamEvent, None]:
        queue = self._streams.get(task_uuid)
        if queue is None:
            yield ScriptGenStreamEvent(
                event="error",
                task_uuid=task_uuid,
                case_id=0,
                message="任务不存在或已结束",
            )
            return
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    async def _run_generation(
        self,
        task_uuid: str,
        case_id: int,
        position_serial: str,
        code_serial: str,
        llm_provider: str | None,
    ) -> None:
        runtime = script_gen_registry.get(task_uuid)
        async with async_session() as db:
            case = await self._load_case(db, case_id)
            natural_steps = [s for s in case.steps if not is_tool_step(s.step_type)]
            total = len(natural_steps)

            pos_run, code_run = await self._init_dual_runs(
                db,
                case,
                position_serial=position_serial,
                code_serial=code_serial,
                llm_provider=llm_provider,
            )
            await agent_repository.add_log(
                db,
                pos_run,
                "system",
                "双脚本生成 · Position 路径开始",
                detail={"task_uuid": task_uuid, "serial": position_serial},
            )
            await agent_code_repository.add_log(
                db,
                code_run,
                "system",
                "双脚本生成 · Code 路径开始",
                detail={"task_uuid": task_uuid, "serial": code_serial},
            )
            await sync_task_status(
                db,
                task_uuid,
                progress={
                    "completed_steps": 0,
                    "total_steps": total,
                    "position_run_uuid": pos_run.run_uuid,
                    "code_run_uuid": code_run.run_uuid,
                    "message": f"双路径执行记录已创建 Position={position_serial} Code={code_serial}",
                },
                commit=True,
            )
            await db.commit()
            pos_run = await agent_repository.get_run_by_uuid(db, pos_run.run_uuid)
            code_run = await agent_code_repository.get_run_by_uuid(db, code_run.run_uuid)
            assert pos_run is not None and code_run is not None

            pos_run_uuid = pos_run.run_uuid
            code_run_uuid = code_run.run_uuid

            pos_failed, code_failed = await asyncio.gather(
                self._run_position_pipeline(
                    task_uuid=task_uuid,
                    case_id=case_id,
                    run_uuid=pos_run_uuid,
                    serial=position_serial,
                    llm_provider=llm_provider,
                    total=total,
                    runtime=runtime,
                ),
                self._run_code_pipeline(
                    task_uuid=task_uuid,
                    case_id=case_id,
                    run_uuid=code_run_uuid,
                    serial=code_serial,
                    llm_provider=llm_provider,
                    total=total,
                    runtime=runtime,
                ),
            )
            generation_failed = bool(pos_failed or code_failed)
            pos_run = await agent_repository.get_run_by_uuid(db, pos_run_uuid)
            code_run = await agent_code_repository.get_run_by_uuid(db, code_run_uuid)
            assert pos_run is not None and code_run is not None

            await self._finalize_dual_runs(
                db, pos_run, code_run, completed_steps=total, failed=generation_failed
            )
            await sync_task_status(
                db,
                task_uuid,
                status="completed" if not generation_failed else "failed",
                progress={
                    "completed_steps": total,
                    "total_steps": total,
                    "position_run_uuid": pos_run.run_uuid,
                    "code_run_uuid": code_run.run_uuid,
                    "message": "生成完成",
                },
                commit=True,
            )
            await self._emit(task_uuid, "completed", case_id, message="双脚本生成完成")

    async def _handle_tool_step(
        self,
        db: AsyncSession,
        step: CaseStep,
        position_serial: str,
        code_serial: str,
        task_uuid: str,
        case_id: int,
    ) -> None:
        from app.agent_test_service.schemas import StepExecutionRecord

        record = StepExecutionRecord(
            step_order=step.step_order,
            step_type=step.step_type,
            description=step.description,
            metadata=json.loads(step.metadata_json) if step.metadata_json else None,
        )
        pos_result = await agent_tools.run_for_step(record, serial=position_serial)
        code_result = await agent_tools.run_for_step(record, serial=code_serial)
        if not pos_result.success or not code_result.success:
            step.script_status = "failed"
            await db.commit()
            raise RuntimeError(
                pos_result.message if not pos_result.success else code_result.message
            )
        step.position_script_json = pos_result.intent.model_dump_json() if pos_result.intent else None
        step.code_script_json = json.dumps(
            {"code_line": "skip", "reasoning": code_result.message}, ensure_ascii=False
        )
        step.script_status = "ready"
        step.script_generated_at = datetime.now(timezone.utc)
        await db.commit()
        await self._emit(
            task_uuid,
            "step_executed",
            case_id,
            step_order=step.step_order,
            message=f"工具步骤已在双设备执行（{position_serial}, {code_serial}）",
        )

    async def _update_step_status(self, db: AsyncSession, step: CaseStep, status: str) -> None:
        step.script_status = status
        await db.commit()

    async def _load_case(self, db: AsyncSession, case_id: int) -> Case:
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).where(Case.id == case_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            raise RuntimeError("Case 不存在")
        return case


script_generation_service = ScriptGenerationService()
