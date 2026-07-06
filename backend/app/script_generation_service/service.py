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
from app.agent_test_service.tools import agent_tools, is_tool_step
from app.database import async_session
from app.models.case import Case, CaseStep
from app.platform_service.task_service import register_platform_task, sync_task_status
from app.script_generation_service.registry import script_gen_registry
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

    def _emit(self, task_uuid: str, event: str, case_id: int, **kwargs) -> None:
        payload = ScriptGenStreamEvent(
            event=event,
            task_uuid=task_uuid,
            case_id=case_id,
            step_order=kwargs.get("step_order"),
            message=kwargs.get("message", ""),
            detail=kwargs.get("detail"),
        )
        queue = self._streams.get(task_uuid)
        if queue:
            queue.put_nowait(payload)

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
        self._emit(
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

            for index, step in enumerate(natural_steps):
                if runtime and runtime.cancelled:
                    await sync_task_status(db, task_uuid, status="cancelled", commit=True)
                    self._emit(task_uuid, "cancelled", case_id, message="已取消")
                    return

                await self._update_step_status(db, step, "generating")
                self._emit(
                    task_uuid,
                    "step_start",
                    case_id,
                    step_order=step.step_order,
                    message=step.description[:120] or f"步骤 {step.step_order + 1}",
                    detail={"description": step.description},
                )
                await sync_task_status(
                    db,
                    task_uuid,
                    progress={
                        "completed_steps": index,
                        "total_steps": total,
                        "current_step": step.step_order,
                        "message": f"生成步骤 {step.step_order + 1}",
                    },
                    commit=True,
                )

                try:
                    if is_tool_step(step.step_type):
                        await self._handle_tool_step(
                            db, step, position_serial, code_serial, task_uuid, case_id
                        )
                        continue

                    pos_image, pos_w, pos_h = await action_executor.capture_screen(position_serial)
                    code_image, code_w, code_h = await action_executor.capture_screen(code_serial)
                    ui_xml = await dump_ui_xml_async(code_serial)

                    self._emit(
                        task_uuid,
                        "capture_before",
                        case_id,
                        step_order=step.step_order,
                        message="已截取双设备执行前屏幕",
                        detail={
                            "position": {
                                "serial": position_serial,
                                "before_image": pos_image,
                                "width": pos_w,
                                "height": pos_h,
                            },
                            "code": {
                                "serial": code_serial,
                                "before_image": code_image,
                                "width": code_w,
                                "height": code_h,
                            },
                        },
                    )

                    intent_request = AnalyzeIntentRequest(
                        step_description=step.description,
                        screen_image=pos_image,
                        screen_width=pos_w,
                        screen_height=pos_h,
                        llm_provider=llm_provider,
                    )
                    code_request = AnalyzeCodeRequest(
                        step_description=step.description,
                        screen_image=code_image,
                        screen_width=code_w,
                        screen_height=code_h,
                        ui_xml=ui_xml,
                        llm_provider=llm_provider,
                    )

                    intent, generated = await asyncio.gather(
                        intent_analyzer.analyze(intent_request, provider=llm_provider),
                        code_generator.analyze(code_request, provider=llm_provider),
                    )

                    refined_intent = await refine_tap_intent(
                        intent,
                        step_description=step.description,
                        serial=position_serial,
                        screen_height=pos_h,
                        screen_width=pos_w,
                    )

                    step.position_script_json = refined_intent.model_dump_json()
                    generated.template_path = str(
                        render_step_test_file(
                            run_uuid=task_uuid,
                            step_order=step.step_order,
                            description=step.description,
                            serial=code_serial,
                            code_line=generated.code_line,
                        )
                    )
                    step.code_script_json = generated.model_dump_json()
                    step.script_generated_at = datetime.now(timezone.utc)
                    step.script_status = "ready"
                    await db.commit()

                    pos_before_annotated = annotate_before_image(pos_image, refined_intent)

                    self._emit(
                        task_uuid,
                        "scripts_ready",
                        case_id,
                        step_order=step.step_order,
                        message="双脚本已生成",
                        detail={
                            "position": {
                                "serial": position_serial,
                                "before_image": pos_image,
                                "before_image_annotated": pos_before_annotated,
                                "script": refined_intent.model_dump(),
                            },
                            "code": {
                                "serial": code_serial,
                                "before_image": code_image,
                                "script": generated.model_dump(),
                            },
                        },
                    )

                    async def execute_on_position() -> tuple[str, str | None]:
                        if refined_intent.action == "skip":
                            return pos_image, None
                        try:
                            pos_dw, pos_dh = await action_executor.get_device_screen_size(position_serial)
                            mapped = action_executor.map_coordinates(
                                refined_intent,
                                image_width=pos_w,
                                image_height=pos_h,
                                device_width=pos_dw,
                                device_height=pos_dh,
                            )
                            logger.info(
                                "[script_gen] Position 执行 step=%d serial=%s raw=(%s,%s) mapped=(%s,%s) image=%dx%d device=%dx%d",
                                step.step_order,
                                position_serial,
                                refined_intent.x,
                                refined_intent.y,
                                mapped.x,
                                mapped.y,
                                pos_w,
                                pos_h,
                                pos_dw,
                                pos_dh,
                            )
                            await action_executor.execute(mapped, serial=position_serial)
                            after, _, _ = await action_executor.capture_after_screen(position_serial)
                            return after, None
                        except Exception as exc:
                            logger.warning(
                                "[script_gen] Position 设备执行失败 step=%d serial=%s: %s",
                                step.step_order,
                                position_serial,
                                exc,
                            )
                            return pos_image, str(exc)[-400:]

                    async def execute_on_code() -> tuple[str, str | None]:
                        line = (generated.code_line or "").strip()
                        if not line or line == "d.sleep(0.5)":
                            return code_image, None
                        try:
                            exec_result = await code_executor.execute(
                                line,
                                serial=code_serial,
                                test_file=None,
                            )
                            generated.execution_output = exec_result.execution_output
                            generated.pytest_exit_code = exec_result.pytest_exit_code
                            generated.confidence = exec_result.confidence
                            generated.reasoning = exec_result.reasoning
                            if exec_result.pytest_exit_code not in (None, 0):
                                err = (exec_result.execution_output or "Code 执行失败")[-400:]
                                logger.warning(
                                    "[script_gen] Code 设备执行失败 step=%d serial=%s",
                                    step.step_order,
                                    code_serial,
                                )
                                return code_image, err
                            after, _, _ = await action_executor.capture_after_screen(code_serial)
                            return after, None
                        except Exception as exc:
                            logger.warning(
                                "[script_gen] Code 设备执行异常 step=%d serial=%s: %s",
                                step.step_order,
                                code_serial,
                                exc,
                            )
                            return code_image, str(exc)[-400:]

                    self._emit(
                        task_uuid,
                        "executing",
                        case_id,
                        step_order=step.step_order,
                        message=f"双设备并行执行 Position={position_serial} Code={code_serial}",
                        detail={
                            "position_serial": position_serial,
                            "code_serial": code_serial,
                        },
                    )

                    (pos_after, pos_exec_error), (code_after, code_exec_error) = await asyncio.gather(
                        execute_on_position(),
                        execute_on_code(),
                    )

                    step.code_script_json = generated.model_dump_json()
                    await db.commit()

                    parts = [f"步骤 {step.step_order + 1} 完成"]
                    if pos_exec_error:
                        parts.append(f"Position({position_serial}) 未通过")
                    if code_exec_error:
                        parts.append(f"Code({code_serial}) 未通过")

                    self._emit(
                        task_uuid,
                        "step_executed",
                        case_id,
                        step_order=step.step_order,
                        message=" · ".join(parts),
                        detail={
                            "position": {
                                "serial": position_serial,
                                "after_image": pos_after,
                                "exec_error": pos_exec_error,
                            },
                            "code": {
                                "serial": code_serial,
                                "after_image": code_after,
                                "exec_error": code_exec_error,
                                "script": generated.model_dump(),
                            },
                        },
                    )
                except Exception as exc:
                    step.script_status = "failed"
                    await db.commit()
                    await sync_task_status(
                        db, task_uuid, status="failed", error=str(exc), commit=True
                    )
                    self._emit(
                        task_uuid,
                        "error",
                        case_id,
                        step_order=step.step_order,
                        message=str(exc),
                    )
                    return

            await sync_task_status(
                db,
                task_uuid,
                status="completed",
                progress={"completed_steps": total, "total_steps": total, "message": "生成完成"},
                commit=True,
            )
            self._emit(task_uuid, "completed", case_id, message="双脚本生成完成")

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
        self._emit(
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
