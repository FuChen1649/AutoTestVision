import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_test_code_service.code_generator import code_generator
from app.agent_test_code_service.harness import code_harness_graph, code_harness_run_config
from app.agent_test_code_service.repository import agent_code_repository
from app.agent_test_code_service import run_registry as code_run_registry
from app.agent_test_code_service.schemas import (
    AnalyzeCodeRequest,
    CodeBatchListItem,
    CodeBatchStateResponse,
    CodeRunStateResponse,
    CodeStepAdvanceResponse,
    CodeStepExecutionRecord,
    CodeStreamEvent,
    GeneratedStepCode,
    StartCodeBatchRequest,
    StartCodeRunRequest,
)
from app.agent_test_code_service.state import CodeHarnessState, merge_records, utc_now
from app.agent_test_service import log_stream
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import default_provider, probe_providers
from app.agent_test_service.schemas import CaseListItem, ProviderInfo, ProvidersResponse
from app.agent_test_service.tools import agent_tools, parse_step_metadata
from app.database import async_session
from app.models.agent_code import AgentCodeBatchRun, AgentCodeRun
from app.models.case import Case
from app.services.adb import adb_service

logger = get_agent_logger()


class AgentTestCodeService:
    async def list_cases(self, db: AsyncSession, limit: int = 10) -> list[CaseListItem]:
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).order_by(Case.updated_at.desc()).limit(limit)
        )
        return [
            CaseListItem(
                id=case.id,
                name=case.name,
                step_count=len(case.steps),
                updated_at=case.updated_at,
            )
            for case in result.scalars().all()
        ]

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

    async def analyze_code(self, request: AnalyzeCodeRequest) -> GeneratedStepCode:
        return await code_generator.analyze(request, provider=request.llm_provider)

    async def start_run(self, payload: StartCodeRunRequest, db: AsyncSession) -> CodeRunStateResponse:
        case = await self._load_case(payload.case_id, db)
        serial = payload.serial or adb_service.get_active_serial()
        if not serial:
            devices = adb_service.list_devices()
            if not devices:
                raise RuntimeError("未连接设备")
            serial = devices[0].serial
            adb_service.set_active_device(serial)

        provider = payload.llm_provider or default_provider()
        run = await agent_code_repository.create_run(
            db,
            case,
            serial,
            payload.max_retries,
            llm_provider=provider,
            enable_verifier=payload.enable_verifier,
        )
        await agent_code_repository.add_log(
            db,
            run,
            "system",
            f"已创建 AgentTest_Code 运行实例，来源 Case #{case.id}",
            detail={"script_saved": bool(case.script_content), "llm_provider": provider},
        )
        await agent_code_repository.commit(db)
        run = await agent_code_repository.get_run_by_uuid(db, run.run_uuid)
        assert run is not None
        return agent_code_repository.to_response(run)

    async def get_run(self, run_uuid: str, db: AsyncSession) -> CodeRunStateResponse | None:
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        return agent_code_repository.to_response(run) if run else None

    async def cancel_run(self, run_uuid: str, db: AsyncSession) -> CodeRunStateResponse:
        code_run_registry.request_cancel(run_uuid)
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        if run.status in {"completed", "failed", "cancelled"}:
            return agent_code_repository.to_response(run)
        await agent_code_repository.update_run_fields(db, run, status="cancelled", error="用户中止")
        await agent_code_repository.add_log(db, run, "system", "运行已中止")
        await agent_code_repository.commit(db)
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        assert run is not None
        return agent_code_repository.to_response(run)

    async def advance_step(self, run_uuid: str, db: AsyncSession) -> CodeStepAdvanceResponse:
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")
        state = self._to_harness_state(run)
        state["status"] = "running"
        await agent_code_repository.update_run_fields(db, run, status="running")
        await agent_code_repository.commit(db)
        result = await code_harness_graph.ainvoke(state, config=code_harness_run_config(state))
        await self._sync_state_to_db(db, run_uuid, result)
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        assert run is not None
        finished = run.status in {"completed", "failed", "cancelled"}
        return CodeStepAdvanceResponse(
            run=agent_code_repository.to_response(run),
            finished=finished,
            message="步骤执行完成" if not finished else f"运行状态：{run.status}",
        )

    async def stream_run(self, run_uuid: str, db: AsyncSession) -> AsyncGenerator[str, None]:
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            raise RuntimeError("运行实例不存在")

        state = self._to_harness_state(run)
        await agent_code_repository.update_run_fields(db, run, status="running")
        log_stream.set_context(run_uuid, None)
        await agent_code_repository.add_log(db, run, "system", "开始执行 AgentTest_Code Harness")
        await agent_code_repository.commit(db)

        live_queue = log_stream.subscribe(run_uuid)
        code_run_registry.register(run_uuid)
        yield self._sse(CodeStreamEvent(type="start", run=agent_code_repository.to_response(run)))

        out_queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        sentinel = ("__end__", None)

        async def feed_harness() -> None:
            try:
                config = code_harness_run_config(state)
                async for event in code_harness_graph.astream(state, stream_mode="updates", config=config):
                    if code_run_registry.is_cancel_requested(run_uuid):
                        break
                    await out_queue.put(("harness", event))
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.exception("[code_service:stream_run] harness 异常 run_id=%s", run_uuid)
                await out_queue.put(("error", exc))
            finally:
                await out_queue.put(sentinel)

        async def feed_live_logs() -> None:
            try:
                while True:
                    log_item = await live_queue.get()
                    await out_queue.put(("live", log_item))
            except asyncio.CancelledError:
                pass

        harness_task = asyncio.create_task(feed_harness())
        code_run_registry.set_harness_task(run_uuid, harness_task)
        live_task = asyncio.create_task(feed_live_logs())

        merged_state = state
        should_stop = False
        try:
            while not should_stop:
                try:
                    kind, payload = await asyncio.wait_for(out_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    if code_run_registry.is_cancel_requested(run_uuid) and not harness_task.done():
                        harness_task.cancel()
                    continue

                if kind == "__end__":
                    break
                if kind == "live":
                    yield self._sse(CodeStreamEvent(type="log", logs=[payload]))  # type: ignore[list-item]
                    continue
                if kind == "error":
                    exc = payload  # type: ignore[assignment]
                    error_msg = str(exc) or exc.__class__.__name__
                    run_row = await agent_code_repository.get_run_by_uuid(db, run_uuid)
                    if run_row and run_row.status == "running":
                        await agent_code_repository.update_run_fields(
                            db, run_row, status="failed", error=error_msg
                        )
                        await agent_code_repository.commit(db)
                    yield self._sse(
                        CodeStreamEvent(
                            type="error",
                            message=error_msg,
                            run=await self.get_run(run_uuid, db),
                        )
                    )
                    should_stop = True
                    break

                event = payload  # type: ignore[assignment]
                for _node, update in event.items():  # type: ignore[union-attr]
                    merged_state = self._merge_state(merged_state, update)
                    await self._sync_state_to_db(db, run_uuid, merged_state)
                    run_resp = await self.get_run(run_uuid, db)
                    yield self._sse(CodeStreamEvent(type="progress", run=run_resp))
                    if run_resp and run_resp.status in {"failed", "cancelled"}:
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
            code_run_registry.release(run_uuid)

        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if run and code_run_registry.is_cancel_requested(run_uuid):
            await agent_code_repository.update_run_fields(db, run, status="cancelled", error="用户中止")
            await agent_code_repository.commit(db)
        elif run and run.status == "running":
            failed_step = next((s for s in run.steps if s.status == "failed"), None)
            if failed_step:
                await agent_code_repository.update_run_fields(
                    db,
                    run,
                    status="failed",
                    error=failed_step.error or "步骤执行失败",
                )
            else:
                await agent_code_repository.update_run_fields(db, run, status="completed")
            await agent_code_repository.commit(db)

        run_resp = await self.get_run(run_uuid, db)
        yield self._sse(
            CodeStreamEvent(
                type="done",
                run=run_resp,
                message=f"执行结束：{run_resp.status if run_resp else 'unknown'}",
            )
        )

    async def start_batch(
        self, payload: StartCodeBatchRequest, db: AsyncSession
    ) -> CodeBatchStateResponse:
        batch = AgentCodeBatchRun(
            batch_uuid=str(uuid.uuid4()),
            status="running",
            llm_provider=payload.llm_provider or default_provider(),
            enable_verifier=payload.enable_verifier,
            case_ids_json=json.dumps(payload.case_ids),
        )
        db.add(batch)
        await db.flush()

        results = []
        for case_id in payload.case_ids:
            run_resp = await self.start_run(
                StartCodeRunRequest(
                    case_id=case_id,
                    serial=payload.serial,
                    llm_provider=payload.llm_provider,
                    enable_verifier=payload.enable_verifier,
                    max_retries=payload.max_retries,
                ),
                db,
            )
            async for _ in self.stream_run(run_resp.run_id, db):
                pass
            final = await self.get_run(run_resp.run_id, db)
            results.append(
                {
                    "case_id": case_id,
                    "run_id": run_resp.run_id,
                    "status": final.status if final else "failed",
                }
            )

        batch.status = "completed"
        await db.commit()
        return CodeBatchStateResponse(
            batch_id=batch.batch_uuid,
            status=batch.status,
            llm_provider=batch.llm_provider,
            enable_verifier=batch.enable_verifier,
            results=results,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    async def list_batches(self, db: AsyncSession, limit: int = 20) -> list[CodeBatchListItem]:
        result = await db.execute(
            select(AgentCodeBatchRun).order_by(AgentCodeBatchRun.created_at.desc()).limit(limit)
        )
        items = []
        for batch in result.scalars().all():
            case_ids = json.loads(batch.case_ids_json or "[]")
            items.append(
                CodeBatchListItem(
                    batch_id=batch.batch_uuid,
                    status=batch.status,
                    case_count=len(case_ids),
                    llm_provider=batch.llm_provider,
                    created_at=batch.created_at,
                    updated_at=batch.updated_at,
                )
            )
        return items

    async def _load_case(self, case_id: int, db: AsyncSession) -> Case:
        result = await db.execute(
            select(Case).options(selectinload(Case.steps)).where(Case.id == case_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            raise RuntimeError("Case 不存在")
        if not case.steps:
            raise RuntimeError("Case 没有步骤")
        return case

    def _to_harness_state(self, run: AgentCodeRun) -> CodeHarnessState:
        steps: list[CodeStepExecutionRecord] = []
        for step in sorted(run.steps, key=lambda item: item.step_order):
            generated = None
            verification = None
            if step.generated_code_json:
                generated = GeneratedStepCode.model_validate_json(step.generated_code_json)
                generated.template_path = step.template_path
                generated.execution_output = step.execution_output
            if step.verification_json:
                from app.agent_test_service.schemas import VerificationResult

                verification = VerificationResult.model_validate_json(step.verification_json)
            steps.append(
                CodeStepExecutionRecord(
                    step_order=step.step_order,
                    step_type=step.step_type,
                    description=step.description,
                    status=step.status,  # type: ignore[arg-type]
                    generated_code=generated,
                    verification=verification,
                    before_image=step.before_image,
                    before_image_annotated=step.before_image_annotated,
                    after_image=step.after_image,
                    ui_xml_preview=(step.ui_xml or "")[:500] if step.ui_xml else None,
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
            "script_content": run.script_content,
            "serial": run.serial,
            "status": run.status,
            "current_step_index": run.current_step_index,
            "total_steps": run.total_steps,
            "retry_count": run.retry_count,
            "max_retries": run.max_retries,
            "error": run.error,
            "llm_provider": run.llm_provider,
            "enable_verifier": bool(run.enable_verifier),
            "steps": steps,
            "should_continue": run.status not in {"completed", "failed", "cancelled"},
            "created_at": run.created_at,
            "updated_at": utc_now(),
        }

    def _merge_state(self, state: CodeHarnessState, update: CodeHarnessState) -> CodeHarnessState:
        merged = {**state, **update}
        if update.get("steps"):
            merged["steps"] = merge_records(state.get("steps", []), update["steps"])
        return merged

    async def _sync_state_to_db(self, db: AsyncSession, run_uuid: str, state: CodeHarnessState) -> None:
        run = await agent_code_repository.get_run_by_uuid(db, run_uuid)
        if not run:
            return
        step_map = {s.step_order: s for s in run.steps}
        for record in state.get("steps", []):
            orm_step = step_map.get(record.step_order)
            if not orm_step:
                continue
            orm_step.status = record.status
            if record.before_image:
                orm_step.before_image = record.before_image
            if record.before_image_annotated:
                orm_step.before_image_annotated = record.before_image_annotated
            if record.after_image:
                orm_step.after_image = record.after_image
            if record.generated_code:
                orm_step.generated_code_json = json.dumps(
                    record.generated_code.model_dump(), ensure_ascii=False
                )
                orm_step.template_path = record.generated_code.template_path
                orm_step.execution_output = record.generated_code.execution_output
            if record.verification:
                orm_step.verification_json = json.dumps(
                    record.verification.model_dump(), ensure_ascii=False
                )
            orm_step.error = record.error
        if state.get("ui_xml"):
            idx = state.get("current_step_index", 0)
            if idx < len(run.steps):
                run.steps[idx].ui_xml = state["ui_xml"]
        await agent_code_repository.update_run_fields(
            db,
            run,
            current_step_index=state.get("current_step_index", run.current_step_index),
            retry_count=state.get("retry_count", run.retry_count),
            status=state.get("status", run.status),
            error=state.get("error"),
        )
        await agent_code_repository.commit(db)

    def _sse(self, event: CodeStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"


agent_test_code_service = AgentTestCodeService()
