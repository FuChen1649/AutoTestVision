import asyncio
import json
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.harness import harness_graph, harness_run_config
from app.agent_test_service.action_executor import action_executor
from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.intent_analyzer import intent_analyzer
from app.agent_test_service.llm_factory import default_provider, probe_providers
from app.agent_test_service import log_stream
from app.agent_test_service.repository import agent_repository
from app.agent_test_service.schemas import (
    ActionIntent,
    AgentLogItem,
    AgentLogsResponse,
    AnalyzeIntentRequest,
    CaseListItem,
    DeviceReplayStreamEvent,
    ProviderInfo,
    ProvidersResponse,
    RunStateResponse,
    StartRunRequest,
    StepAdvanceResponse,
    StepExecutionRecord,
    StreamEvent,
)
from app.agent_test_service.tools import agent_tools, is_tool_step, parse_step_metadata
from app.agent_test_service.state import HarnessAgentState, merge_records, utc_now
from app.models.agent import AgentRun
from app.models.case import Case
from app.services.adb import adb_service

logger = get_agent_logger()


class AgentTestService:
    async def list_cases(self, db: AsyncSession, limit: int = 10) -> list[CaseListItem]:
        logger.info("[service:list_cases] limit=%d", limit)
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).order_by(Case.updated_at.desc()).limit(limit)
        )
        cases = list(result.scalars().all())
        logger.info("[service:list_cases] 返回 %d 条", len(cases))
        return [
            CaseListItem(
                id=case.id,
                name=case.name,
                step_count=len(case.steps),
                updated_at=case.updated_at,
            )
            for case in cases
        ]

    async def analyze_intent(self, request: AnalyzeIntentRequest) -> ActionIntent:
        logger.info("[service:analyze_intent] desc=%s", request.step_description[:80])
        intent = await intent_analyzer.analyze(request)
        logger.info("[service:analyze_intent] action=%s confidence=%.2f", intent.action, intent.confidence)
        return intent

    async def start_run(self, payload: StartRunRequest, db: AsyncSession) -> RunStateResponse:
        logger.info(
            "[service:start_run] case_id=%d serial=%s provider=%s",
            payload.case_id,
            payload.serial,
            payload.llm_provider,
        )
        case = await self._load_case(payload.case_id, db)
        serial = payload.serial or adb_service.get_active_serial()
        if not serial:
            devices = adb_service.list_devices()
            if not devices:
                raise RuntimeError("未连接设备")
            serial = devices[0].serial
            adb_service.set_active_device(serial)

        resolved_provider = payload.llm_provider or default_provider()
        run = await agent_repository.create_run(
            db,
            case,
            serial,
            payload.max_retries,
            llm_provider=resolved_provider,
            enable_verifier=payload.enable_verifier,
        )
        await agent_repository.add_log(
            db,
            run,
            "system",
            f"已创建 Agent 运行实例，来源 Case #{case.id}",
            detail={
                "case_name": case.name,
                "llm_provider": resolved_provider,
                "enable_verifier": payload.enable_verifier,
            },
        )
        await agent_repository.commit(db)
        run = await agent_repository.get_run_by_uuid(db, run.run_uuid)
        assert run is not None
        logger.info(
            "[service:start_run] run_id=%s steps=%d provider=%s",
            run.run_uuid,
            run.total_steps,
            run.llm_provider,
        )
        return agent_repository.to_response(run)

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
        # 默认 provider：优先 settings 指定且实测可达；否则取第一个可达；都没有则 None
        configured = default_provider()
        resolved_default: str | None = None
        if configured and any(info.available and info.id == configured for info in infos):
            resolved_default = configured
        else:
            for info in infos:
                if info.available:
                    resolved_default = info.id
                    break
        return ProvidersResponse(providers=infos, default=resolved_default)

    async def get_run(self, run_uuid: str, db: AsyncSession) -> RunStateResponse | None:
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return None
        return agent_repository.to_response(run)

    async def get_logs(
        self, run_uuid: str, db: AsyncSession, agent_type: str | None = None
    ) -> AgentLogsResponse:
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        return AgentLogsResponse(
            run_id=run_uuid,
            logs=agent_repository.logs_to_items(run, agent_type=agent_type),
        )

    async def advance_step(self, run_uuid: str, db: AsyncSession) -> StepAdvanceResponse:
        logger.info("[service:advance_step] run_id=%s", run_uuid)
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        if run.status in {"completed", "failed", "cancelled"}:
            return StepAdvanceResponse(
                run=agent_repository.to_response(run),
                finished=True,
                message="运行已结束",
            )

        state = self._to_harness_state(run)
        state["status"] = "running"
        await agent_repository.update_run_fields(db, run, status="running")
        await self._recover_scene_before_run(db, run)
        await agent_repository.commit(db)

        result = await harness_graph.ainvoke(state, config=harness_run_config(state))
        await self._sync_state_to_db(db, run_uuid, result)
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        assert run is not None
        finished = run.status in {"completed", "failed", "cancelled"}
        return StepAdvanceResponse(
            run=agent_repository.to_response(run),
            finished=finished,
            message="步骤执行完成" if not finished else f"运行状态：{run.status}",
        )

    async def stream_run(self, run_uuid: str, db: AsyncSession) -> AsyncGenerator[str, None]:
        logger.info("[service:stream_run] run_id=%s", run_uuid)
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")

        state = self._to_harness_state(run)
        await agent_repository.update_run_fields(db, run, status="running")
        log_stream.set_context(run_uuid, None)
        await self._recover_scene_before_run(db, run)
        await agent_repository.add_log(db, run, "system", "开始执行 Agent Harness 流程")
        await agent_repository.commit(db)

        live_queue = log_stream.subscribe(run_uuid)

        yield self._sse(StreamEvent(type="start", run=agent_repository.to_response(run)))

        # 把 harness 事件塞进同一个 "out" 队列，便于和 live_queue 合流
        out_queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        SENTINEL = ("__end__", None)

        async def feed_harness() -> None:
            try:
                config = harness_run_config(state)
                logger.info(
                    "[service:stream_run] recursion_limit=%d run_id=%s steps=%d retries=%d",
                    config["recursion_limit"],
                    run_uuid,
                    state.get("total_steps", 0),
                    state.get("max_retries", 0),
                )
                async for event in harness_graph.astream(state, stream_mode="updates", config=config):
                    await out_queue.put(("harness", event))
            except Exception as exc:
                logger.exception("[service:stream_run] harness 异常 run_id=%s", run_uuid)
                await out_queue.put(("error", exc))
            finally:
                await out_queue.put(SENTINEL)

        async def feed_live_logs() -> None:
            try:
                while True:
                    log_item = await live_queue.get()
                    await out_queue.put(("live", log_item))
            except asyncio.CancelledError:
                pass

        harness_task = asyncio.create_task(feed_harness())
        live_task = asyncio.create_task(feed_live_logs())

        try:
            should_stop = False
            while not should_stop:
                kind, payload = await out_queue.get()
                if kind == "__end__":
                    break
                if kind == "error":
                    exc = payload  # type: ignore[assignment]
                    error_msg = str(exc)
                    run = await agent_repository.get_run_by_uuid(db, run_uuid)
                    if run and run.status == "running":
                        await agent_repository.update_run_fields(
                            db, run, status="failed", error=error_msg
                        )
                        await agent_repository.add_log(
                            db, run, "system", f"执行异常：{error_msg}"
                        )
                        await agent_repository.commit(db)
                    run = await agent_repository.get_run_by_uuid(db, run_uuid)
                    yield self._sse(
                        StreamEvent(
                            type="error",
                            run=agent_repository.to_response(run) if run else None,
                            message=error_msg,
                        )
                    )
                    should_stop = True
                    break
                if kind == "live":
                    # 实时日志：单独包一个事件发出去，前端走同一条 logs 通道
                    yield self._sse(StreamEvent(type="log", logs=[payload]))  # type: ignore[list-item]
                    continue

                # harness 节点更新
                event = payload  # type: ignore[assignment]
                for node_name, update in event.items():  # type: ignore[union-attr]
                    logger.debug("[service:stream_run] node=%s run_id=%s", node_name, run_uuid)
                    state = self._merge_state(state, update)
                    new_logs = await self._persist_node_update(db, run_uuid, node_name, state)
                    run = await agent_repository.get_run_by_uuid(db, run_uuid)
                    if not run:
                        should_stop = True
                        break
                    yield self._sse(
                        StreamEvent(
                            type="node",
                            node=node_name,
                            run=agent_repository.to_response(run),
                            logs=new_logs,
                        )
                    )
                    if run.status in {"failed", "cancelled"}:
                        should_stop = True
                        break
        finally:
            live_task.cancel()
            try:
                await live_task
            except asyncio.CancelledError:
                pass
            if not harness_task.done():
                harness_task.cancel()
                try:
                    await harness_task
                except (asyncio.CancelledError, Exception):
                    pass
            log_stream.release(run_uuid)
            log_stream.set_context(None, None)

        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        assert run is not None
        if run.status == "running":
            await agent_repository.update_run_fields(db, run, status="completed")
            await agent_repository.commit(db)
            run = await agent_repository.get_run_by_uuid(db, run_uuid)
        yield self._sse(
            StreamEvent(
                type="done",
                run=agent_repository.to_response(run) if run else None,
                message=f"执行结束：{run.status if run else 'unknown'}",
            )
        )

    async def cancel_run(self, run_uuid: str, db: AsyncSession) -> bool:
        logger.info("[service:cancel_run] run_id=%s", run_uuid)
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return False
        await agent_repository.update_run_fields(db, run, status="cancelled")
        await agent_repository.add_log(db, run, "system", "运行已取消")
        await agent_repository.commit(db)
        return True

    async def stream_device_replay(
        self,
        run_uuid: str,
        db: AsyncSession,
        step_interval_ms: int = 3000,
    ) -> AsyncGenerator[str, None]:
        logger.info(
            "[service:stream_device_replay] run_id=%s interval_ms=%d",
            run_uuid,
            step_interval_ms,
        )
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        if run.status == "running":
            raise RuntimeError("运行尚未结束，请稍后再试真机回放")

        serial = run.serial or adb_service.get_active_serial()
        if not serial:
            raise RuntimeError("未连接设备")

        state = self._to_harness_state(run)
        successful_steps = [
            step for step in state.get("steps", []) if step.status == "success"
        ]
        successful_steps.sort(key=lambda item: item.step_order)
        if not successful_steps:
            raise RuntimeError("没有执行成功的步骤，无法进行真机回放")

        interval_sec = max(step_interval_ms, 0) / 1000.0
        total = len(successful_steps)

        yield self._device_replay_sse(
            DeviceReplayStreamEvent(
                type="start",
                message=f"准备真机回放，共 {total} 个成功步骤",
                total_steps=total,
            )
        )

        yield self._device_replay_sse(
            DeviceReplayStreamEvent(
                type="recover",
                message="场景恢复：清空后台应用并返回主屏幕…",
            )
        )
        recovery = await agent_tools.recover_scene(serial=serial)
        if not recovery.get("success"):
            yield self._device_replay_sse(
                DeviceReplayStreamEvent(
                    type="error",
                    message=recovery.get("message") or "场景恢复失败",
                )
            )
            return

        yield self._device_replay_sse(
            DeviceReplayStreamEvent(
                type="recover",
                message=recovery.get("message") or "场景恢复完成",
            )
        )

        if interval_sec > 0:
            yield self._device_replay_sse(
                DeviceReplayStreamEvent(
                    type="wait",
                    message=f"等待 {step_interval_ms / 1000:.1f} 秒…",
                )
            )
            await asyncio.sleep(interval_sec)

        for index, step in enumerate(successful_steps):
            action_label = self._describe_replay_action(step)
            yield self._device_replay_sse(
                DeviceReplayStreamEvent(
                    type="step",
                    message=f"执行步骤 {step.step_order + 1}：{step.description}",
                    step_order=step.step_order,
                    step_index=index,
                    total_steps=total,
                    action=action_label,
                )
            )

            try:
                await self._execute_device_replay_step(step, serial=serial)
            except Exception as exc:
                logger.exception(
                    "[service:stream_device_replay] 步骤失败 run_id=%s step=%d",
                    run_uuid,
                    step.step_order,
                )
                yield self._device_replay_sse(
                    DeviceReplayStreamEvent(
                        type="error",
                        message=f"步骤 {step.step_order + 1} 执行失败：{exc}",
                        step_order=step.step_order,
                        step_index=index,
                        total_steps=total,
                    )
                )
                return

            yield self._device_replay_sse(
                DeviceReplayStreamEvent(
                    type="step",
                    message=f"步骤 {step.step_order + 1} 已在设备上执行",
                    step_order=step.step_order,
                    step_index=index,
                    total_steps=total,
                    action=action_label,
                )
            )

            if index < total - 1 and interval_sec > 0:
                yield self._device_replay_sse(
                    DeviceReplayStreamEvent(
                        type="wait",
                        message=f"等待 {step_interval_ms / 1000:.1f} 秒后执行下一步…",
                        step_order=step.step_order,
                        step_index=index,
                        total_steps=total,
                    )
                )
                await asyncio.sleep(interval_sec)

        yield self._device_replay_sse(
            DeviceReplayStreamEvent(
                type="done",
                message=f"真机回放完成，共执行 {total} 个步骤",
                total_steps=total,
            )
        )

    async def _execute_device_replay_step(
        self, step: StepExecutionRecord, *, serial: str
    ) -> None:
        if is_tool_step(step.step_type):
            metadata = step.metadata or {}
            tool_result = await agent_tools.apply_app_permissions(metadata, serial=serial)
            if not tool_result.success:
                raise RuntimeError(tool_result.message)
            return

        intent = step.intent
        if intent is None:
            raise RuntimeError("步骤缺少可执行 action")
        if intent.action == "skip":
            logger.info(
                "[service:stream_device_replay] 跳过无设备操作步骤 step=%d",
                step.step_order,
            )
            return

        await action_executor.execute(intent, serial=serial)

    def _describe_replay_action(self, step: StepExecutionRecord) -> str:
        if is_tool_step(step.step_type):
            package = (step.metadata or {}).get("package")
            return f"tool:{step.step_type}" + (f"({package})" if package else "")

        intent = step.intent
        if not intent:
            return "unknown"
        if intent.action == "skip":
            return "skip"
        if intent.action == "tap":
            return f"tap({intent.x},{intent.y})"
        if intent.action == "long_press":
            return f"long_press({intent.x},{intent.y})"
        if intent.action == "swipe":
            return f"swipe({intent.x},{intent.y})→({intent.x2},{intent.y2})"
        return intent.action

    def _device_replay_sse(self, event: DeviceReplayStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"

    async def _recover_scene_before_run(self, db: AsyncSession, run: AgentRun) -> None:
        if run.current_step_index > 0 or run.status not in {"pending", "running"}:
            return
        recovery = await agent_tools.recover_scene(serial=run.serial)
        await agent_repository.add_log(
            db,
            run,
            "system",
            recovery["message"],
            detail=recovery.get("detail"),
        )
        if not recovery.get("success"):
            logger.warning("[service] 场景恢复未完全成功 run_id=%s", run.run_uuid)

    def _merge_state(self, state: HarnessAgentState, update: HarnessAgentState) -> HarnessAgentState:
        merged = {**state, **update}
        if "steps" in update and update["steps"]:
            merged["steps"] = merge_records(state.get("steps", []), update["steps"])
        return merged

    async def _sync_state_to_db(self, db: AsyncSession, run_uuid: str, state: HarnessAgentState) -> None:
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return

        for step_record in state.get("steps", []):
            fields: dict = {"status": step_record.status}
            if step_record.before_image:
                fields["before_image"] = step_record.before_image
            if step_record.before_image_annotated:
                fields["before_image_annotated"] = step_record.before_image_annotated
            if step_record.after_image:
                fields["after_image"] = step_record.after_image
            if step_record.intent:
                fields["intent"] = step_record.intent
                if step_record.before_image and not step_record.before_image_annotated:
                    fields["before_image_annotated"] = annotate_before_image(
                        step_record.before_image, step_record.intent
                    )
            if step_record.verification:
                fields["verification"] = step_record.verification
            if step_record.error:
                fields["error"] = step_record.error
            await agent_repository.update_step(db, run, step_record.step_order, **fields)

        await agent_repository.update_run_fields(
            db,
            run,
            current_step_index=state.get("current_step_index", run.current_step_index),
            retry_count=state.get("retry_count", run.retry_count),
            status=state.get("status", run.status),
            error=state.get("error"),
        )
        await agent_repository.commit(db)

    async def _persist_node_update(
        self, db: AsyncSession, run_uuid: str, node_name: str, state: HarnessAgentState
    ) -> list[AgentLogItem]:
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return []

        step_index = state.get("current_step_index", 0)
        step_record = None
        if step_index < len(state.get("steps", [])):
            step_record = state["steps"][step_index]

        if node_name == "load_step":
            if step_record:
                await agent_repository.add_log(
                    db,
                    run,
                    "system",
                    f"加载步骤 {step_index + 1}：{step_record.description}",
                    step_order=step_record.step_order,
                )

        elif node_name == "run_tool" and step_record:
            await agent_repository.create_attempt(
                db, run, step_record.step_order, step_record.before_image
            )
            await agent_repository.add_log(
                db,
                run,
                "executor",
                step_record.intent.reasoning if step_record.intent else "工具步骤执行完成",
                step_order=step_record.step_order,
                detail=step_record.intent.model_dump() if step_record.intent else None,
            )
            if step_record.verification:
                await agent_repository.add_log(
                    db,
                    run,
                    "verifier",
                    "验证完成：" + ("成功" if step_record.verification.success else "失败"),
                    step_order=step_record.step_order,
                    detail=step_record.verification.model_dump(),
                )
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                status=step_record.status,
                before_image=step_record.before_image,
                after_image=step_record.after_image,
                intent=step_record.intent,
                verification=step_record.verification,
                error=step_record.error,
            )
            await agent_repository.update_latest_attempt(
                db,
                run,
                step_record.step_order,
                before_image=step_record.before_image,
                after_image=step_record.after_image,
                status=step_record.status,
                error=step_record.error,
            )

        elif node_name == "capture_before" and step_record:
            await agent_repository.create_attempt(
                db, run, step_record.step_order, step_record.before_image
            )
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                status="running",
                before_image=step_record.before_image,
            )

        elif node_name == "analyze_intent" and step_record and step_record.intent:
            intent = step_record.intent
            annotated = annotate_before_image(step_record.before_image or "", intent)
            await agent_repository.add_log(
                db,
                run,
                "intent",
                "开始分析步骤意图",
                step_order=step_record.step_order,
                detail={"description": step_record.description},
            )
            await agent_repository.add_log(
                db,
                run,
                "intent",
                "意图分析完成",
                step_order=step_record.step_order,
                detail=intent.model_dump(),
            )
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                intent=intent,
                before_image_annotated=annotated,
            )
            await agent_repository.update_latest_attempt(
                db,
                run,
                step_record.step_order,
                before_image_annotated=annotated,
            )
            step_record.before_image_annotated = annotated

        elif node_name == "execute_action" and step_record and step_record.intent:
            await agent_repository.add_log(
                db,
                run,
                "executor",
                f"执行操作：{step_record.intent.action}",
                step_order=step_record.step_order,
                detail=step_record.intent.model_dump(),
            )
            await agent_repository.update_step(db, run, step_record.step_order, intent=step_record.intent)

        elif node_name == "capture_after" and step_record:
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                after_image=step_record.after_image,
            )
            await agent_repository.update_latest_attempt(
                db,
                run,
                step_record.step_order,
                after_image=step_record.after_image,
            )

        elif node_name == "skip_verify_step" and step_record and step_record.verification:
            verification = step_record.verification
            await agent_repository.add_log(
                db,
                run,
                "verifier",
                "验证 Agent 已关闭，跳过本步检查",
                step_order=step_record.step_order,
                detail=verification.model_dump(),
            )
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                status=step_record.status,
                verification=verification,
                error=step_record.error,
            )
            await agent_repository.update_latest_attempt(
                db,
                run,
                step_record.step_order,
                status=step_record.status,
                error=step_record.error,
            )

        elif node_name == "verify_step" and step_record and step_record.verification:
            verification = step_record.verification
            await agent_repository.add_log(
                db,
                run,
                "verifier",
                "开始验证步骤执行结果",
                step_order=step_record.step_order,
            )
            await agent_repository.add_log(
                db,
                run,
                "verifier",
                "验证完成：" + ("成功" if verification.success else "失败"),
                step_order=step_record.step_order,
                detail=verification.model_dump(),
            )
            await agent_repository.update_step(
                db,
                run,
                step_record.step_order,
                status=step_record.status,
                verification=verification,
                error=step_record.error,
            )
            await agent_repository.update_latest_attempt(
                db,
                run,
                step_record.step_order,
                status=step_record.status,
                error=step_record.error,
            )

        elif node_name == "advance_state":
            await agent_repository.update_run_fields(
                db,
                run,
                current_step_index=state.get("current_step_index", run.current_step_index),
                retry_count=state.get("retry_count", run.retry_count),
                status=state.get("status", run.status),
                error=state.get("error"),
            )

        elif node_name == "finalize":
            await agent_repository.update_run_fields(
                db,
                run,
                status=state.get("status", "completed"),
                error=state.get("error"),
            )

        await agent_repository.commit(db)
        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return []
        return agent_repository.logs_to_items(run)[-5:]

    def _to_harness_state(self, run: AgentRun) -> HarnessAgentState:
        steps: list[StepExecutionRecord] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            intent = None
            verification = None
            if step.intent_json:
                intent = ActionIntent.model_validate_json(step.intent_json)
            if step.verification_json:
                from app.agent_test_service.schemas import VerificationResult

                verification = VerificationResult.model_validate_json(step.verification_json)
            steps.append(
                StepExecutionRecord(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    status=step.status,
                    intent=intent,
                    verification=verification,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    reference_image=step.reference_image,
                    reference_x=step.reference_x,
                    reference_y=step.reference_y,
                    reference_width=step.reference_width,
                    reference_height=step.reference_height,
                    error=step.error,
                    metadata=parse_step_metadata(step.metadata_json),
                )
            )

        return {
            "run_id": run.run_uuid,
            "case_id": run.source_case_id,
            "case_name": run.case_name,
            "serial": run.serial,
            "status": run.status,
            "current_step_index": run.current_step_index,
            "total_steps": run.total_steps,
            "retry_count": run.retry_count,
            "max_retries": run.max_retries,
            "error": run.error,
            "llm_provider": run.llm_provider,
            "enable_verifier": bool(getattr(run, "enable_verifier", False)),
            "steps": steps,
            "should_continue": run.status not in {"completed", "failed", "cancelled"},
            "created_at": run.created_at,
            "updated_at": utc_now(),
        }

    def _sse(self, event: StreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"

    async def _load_case(self, case_id: int, db: AsyncSession) -> Case:
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).where(Case.id == case_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            raise RuntimeError("Case 不存在")
        if not case.steps:
            raise RuntimeError("Case 没有可执行步骤")
        return case


agent_test_service = AgentTestService()
