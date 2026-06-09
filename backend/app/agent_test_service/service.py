import json
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.harness import harness_graph
from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.intent_analyzer import intent_analyzer
from app.agent_test_service.repository import agent_repository
from app.agent_test_service.schemas import (
    ActionIntent,
    AgentLogItem,
    AgentLogsResponse,
    AnalyzeIntentRequest,
    CaseListItem,
    RunStateResponse,
    StartRunRequest,
    StepAdvanceResponse,
    StepExecutionRecord,
    StreamEvent,
)
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
        logger.info("[service:start_run] case_id=%d serial=%s", payload.case_id, payload.serial)
        case = await self._load_case(payload.case_id, db)
        serial = payload.serial or adb_service.get_active_serial()
        if not serial:
            devices = adb_service.list_devices()
            if not devices:
                raise RuntimeError("未连接设备")
            serial = devices[0].serial
            adb_service.set_active_device(serial)

        run = await agent_repository.create_run(db, case, serial, payload.max_retries)
        await agent_repository.add_log(
            db, run, "system", f"已创建 Agent 运行实例，来源 Case #{case.id}", detail={"case_name": case.name}
        )
        await agent_repository.commit(db)
        run = await agent_repository.get_run_by_uuid(db, run.run_uuid)
        assert run is not None
        logger.info("[service:start_run] run_id=%s steps=%d", run.run_uuid, run.total_steps)
        return agent_repository.to_response(run)

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
        await agent_repository.commit(db)

        result = await harness_graph.ainvoke(state)
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
        await agent_repository.add_log(db, run, "system", "开始执行 Agent Harness 流程")
        await agent_repository.commit(db)

        yield self._sse(StreamEvent(type="start", run=agent_repository.to_response(run)))

        run = await agent_repository.get_run_by_uuid(db, run_uuid)
        async for event in harness_graph.astream(state, stream_mode="updates"):
            should_stop = False
            for node_name, update in event.items():
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
            if should_stop:
                break

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
