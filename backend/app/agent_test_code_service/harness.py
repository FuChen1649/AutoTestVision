"""LangGraph Harness：截图 + XML → 生成 u2 代码 → pytest 执行 → 验证。"""

from pathlib import Path

from langgraph.graph import END, StateGraph

from app.agent_test_code_service.code_annotation import annotate_code_before_image
from app.agent_test_code_service.code_executor import code_executor
from app.agent_test_code_service.code_generator import code_generator, render_step_test_file
from app.agent_test_code_service.schemas import AnalyzeCodeRequest, CodeStepExecutionRecord
from app.agent_test_code_service.state import CodeHarnessState, utc_now
from app.agent_test_service.action_executor import action_executor
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.log_stream import set_context as set_log_context
from app.agent_test_service.schemas import ActionIntent, VerificationResult
from app.agent_test_service.step_verifier import step_verifier
from app.agent_test_service.tools import agent_tools, is_tool_step
from app.agent_test_code_service.ui_dump import dump_ui_xml_async

logger = get_agent_logger()

_NODES_PER_STEP = 7


def code_harness_run_config(state: CodeHarnessState) -> dict[str, int]:
    total = max(state.get("total_steps", 1), 1)
    retries = max(state.get("max_retries", 1), 0) + 1
    return {"recursion_limit": max(total * _NODES_PER_STEP * retries + 15, 50)}


def _current_step(state: CodeHarnessState) -> CodeStepExecutionRecord:
    return state["steps"][state.get("current_step_index", 0)]


def _update_step(state: CodeHarnessState, record: CodeStepExecutionRecord) -> list[CodeStepExecutionRecord]:
    return [record]


async def load_step_node(state: CodeHarnessState) -> CodeHarnessState:
    index = state.get("current_step_index", 0)
    if index >= state.get("total_steps", 0):
        return {"status": "completed", "should_continue": False, "updated_at": utc_now()}
    step = state["steps"][index]
    return {
        "status": "running",
        "current_description": step.description,
        "current_step_type": step.step_type,
        "should_continue": True,
        "updated_at": utc_now(),
    }


def route_after_load_step(state: CodeHarnessState) -> str:
    if is_tool_step(state.get("current_step_type", "natural")):
        return "run_tool"
    return "capture_before"


async def run_tool_node(state: CodeHarnessState) -> CodeHarnessState:
    from app.agent_test_service.schemas import StepExecutionRecord

    step = _current_step(state)
    set_log_context(state.get("run_id"), step.step_order)
    serial = state.get("serial")
    before_image, width, height = await action_executor.capture_screen(serial)
    step.status = "running"
    step.before_image = before_image
    tool_step = StepExecutionRecord(
        step_order=step.step_order,
        step_type=step.step_type,
        description=step.description,
        metadata=step.metadata,
    )
    tool_result = await agent_tools.run_for_step(tool_step, serial=serial)
    step.generated_code = None
    step.verification = tool_result.verification
    step.status = "success" if tool_result.success else "failed"
    step.error = None if tool_result.success else tool_result.message
    after_image, _, _ = await action_executor.capture_after_screen(serial)
    step.after_image = after_image
    return {
        "before_image": before_image,
        "after_image": after_image,
        "screen_width": width,
        "screen_height": height,
        "generated_code": None,
        "verification": step.verification,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def capture_before_node(state: CodeHarnessState) -> CodeHarnessState:
    serial = state.get("serial")
    image, width, height = await action_executor.capture_screen(serial)
    ui_xml = await dump_ui_xml_async(serial)
    step = _current_step(state)
    step.status = "running"
    step.before_image = image
    step.ui_xml_preview = ui_xml[:500] if ui_xml else None
    return {
        "before_image": image,
        "screen_width": width,
        "screen_height": height,
        "ui_xml": ui_xml,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def generate_code_node(state: CodeHarnessState) -> CodeHarnessState:
    step = _current_step(state)
    set_log_context(state.get("run_id"), step.step_order)
    serial = state.get("serial")

    if step.generated_code and step.generated_code.code_line:
        logger.info(
            "[code_harness:generate] run=%s step=%d 使用预生成 Code 脚本",
            state.get("run_id"),
            step.step_order,
        )
        if not step.generated_code.template_path:
            template_path = render_step_test_file(
                run_uuid=state.get("run_id", "unknown"),
                step_order=step.step_order,
                description=step.description,
                serial=serial or "",
                code_line=step.generated_code.code_line,
            )
            step.generated_code.template_path = str(template_path)
        return {
            "generated_code": step.generated_code,
            "steps": _update_step(state, step),
            "updated_at": utc_now(),
        }

    ui_xml = state.get("ui_xml") or ""
    if not ui_xml:
        ui_xml = await dump_ui_xml_async(serial)
    if ui_xml:
        step.ui_xml_preview = ui_xml[:500]

    request = AnalyzeCodeRequest(
        step_description=step.description,
        screen_image=state.get("before_image") or "",
        screen_width=state.get("screen_width", 1080),
        screen_height=state.get("screen_height", 1920),
        ui_xml=ui_xml,
        llm_provider=state.get("llm_provider"),
    )
    generated = await code_generator.analyze(request, provider=state.get("llm_provider"))
    template_path = render_step_test_file(
        run_uuid=state.get("run_id", "unknown"),
        step_order=step.step_order,
        description=step.description,
        serial=serial or "",
        code_line=generated.code_line,
    )
    generated.template_path = str(template_path)
    step.generated_code = generated
    logger.info(
        "[code_harness:generate] run=%s code=%s",
        state.get("run_id"),
        generated.code_line,
    )
    return {
        "ui_xml": ui_xml,
        "generated_code": generated,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def execute_code_node(state: CodeHarnessState) -> CodeHarnessState:
    step = _current_step(state)
    generated = state.get("generated_code") or step.generated_code
    if not generated or not generated.template_path:
        raise RuntimeError("缺少生成的测试文件")
    result = await code_executor.execute(
        generated.code_line,
        serial=state.get("serial") or "",
        test_file=Path(generated.template_path) if generated.template_path else None,
    )
    generated.execution_output = result.execution_output
    generated.pytest_exit_code = result.pytest_exit_code
    generated.confidence = result.confidence
    generated.reasoning = result.reasoning
    step.generated_code = generated
    if step.before_image and not step.before_image_annotated and generated.code_line:
        fallback_x = (
            step.reference_x + step.reference_width // 2
            if step.reference_x is not None and step.reference_width is not None
            else None
        )
        fallback_y = (
            step.reference_y + step.reference_height // 2
            if step.reference_y is not None and step.reference_height is not None
            else None
        )
        device_w, device_h = await action_executor.get_device_screen_size(state.get("serial"))
        annotated = await annotate_code_before_image(
            step.before_image,
            generated.code_line,
            ui_xml=state.get("ui_xml"),
            device_width=device_w,
            device_height=device_h,
            serial=state.get("serial"),
            fallback_x=fallback_x,
            fallback_y=fallback_y,
        )
        if annotated:
            step.before_image_annotated = annotated
    if result.pytest_exit_code != 0:
        step.status = "failed"
        step.error = result.execution_output[-500:] if result.execution_output else "pytest 失败"
    return {
        "generated_code": generated,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def capture_after_node(state: CodeHarnessState) -> CodeHarnessState:
    image, _, _ = await action_executor.capture_after_screen(state.get("serial"))
    step = _current_step(state)
    step.after_image = image
    if step.generated_code and step.generated_code.pytest_exit_code == 0:
        step.status = "running"
    return {
        "after_image": image,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def verify_step_node(state: CodeHarnessState) -> CodeHarnessState:
    step = _current_step(state)
    if step.generated_code and step.generated_code.pytest_exit_code not in (None, 0):
        verification = VerificationResult(
            success=False,
            confidence=0.0,
            reasoning=step.error or "pytest 未通过",
        )
    else:
        verification = await step_verifier.verify(
            step.description,
            ActionIntent(action="tap", x=0, y=0),
            step.before_image or "",
            step.after_image or "",
            provider=state.get("llm_provider"),
        )
    step.verification = verification
    step.status = "success" if verification.success else "failed"
    if not verification.success:
        step.error = verification.reasoning
    return {
        "verification": verification,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def skip_verify_step_node(state: CodeHarnessState) -> CodeHarnessState:
    step = _current_step(state)
    ok = step.generated_code is None or step.generated_code.pytest_exit_code in (None, 0)
    verification = VerificationResult(
        success=ok,
        confidence=1.0 if ok else 0.0,
        reasoning="验证器关闭，按 pytest 结果判定" if ok else (step.error or "pytest 失败"),
    )
    step.verification = verification
    step.status = "success" if ok else "failed"
    return {
        "verification": verification,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def advance_state_node(state: CodeHarnessState) -> CodeHarnessState:
    step = _current_step(state)
    verification = state.get("verification")
    if verification and verification.success:
        next_index = state.get("current_step_index", 0) + 1
        finished = next_index >= state.get("total_steps", 0)
        return {
            "current_step_index": next_index,
            "retry_count": 0,
            "ui_xml": None,
            "status": "completed" if finished else "running",
            "should_continue": not finished,
            "updated_at": utc_now(),
        }
    retry_count = state.get("retry_count", 0) + 1
    if retry_count > state.get("max_retries", 1):
        step.status = "failed"
        return {
            "retry_count": retry_count,
            "status": "failed",
            "should_continue": False,
            "error": step.error or "步骤失败且超过最大重试",
            "steps": _update_step(state, step),
            "updated_at": utc_now(),
        }
    return {"retry_count": retry_count, "ui_xml": None, "should_continue": True, "updated_at": utc_now()}


async def finalize_node(state: CodeHarnessState) -> CodeHarnessState:
    status = state.get("status", "running")
    if status == "running":
        status = "completed"
    return {"status": status, "updated_at": utc_now()}


def route_after_capture_after(state: CodeHarnessState) -> str:
    return "verify_step" if state.get("enable_verifier") else "skip_verify_step"


def route_after_advance(state: CodeHarnessState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    if state.get("should_continue"):
        return "load_step"
    return "finalize"


def build_code_harness_graph():
    graph = StateGraph(CodeHarnessState)
    graph.add_node("load_step", load_step_node)
    graph.add_node("run_tool", run_tool_node)
    graph.add_node("capture_before", capture_before_node)
    graph.add_node("generate_code", generate_code_node)
    graph.add_node("execute_code", execute_code_node)
    graph.add_node("capture_after", capture_after_node)
    graph.add_node("verify_step", verify_step_node)
    graph.add_node("skip_verify_step", skip_verify_step_node)
    graph.add_node("advance_state", advance_state_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("load_step")
    graph.add_conditional_edges(
        "load_step", route_after_load_step, {"run_tool": "run_tool", "capture_before": "capture_before"}
    )
    graph.add_edge("run_tool", "advance_state")
    graph.add_edge("capture_before", "generate_code")
    graph.add_edge("generate_code", "execute_code")
    graph.add_edge("execute_code", "capture_after")
    graph.add_conditional_edges(
        "capture_after",
        route_after_capture_after,
        {"verify_step": "verify_step", "skip_verify_step": "skip_verify_step"},
    )
    graph.add_edge("verify_step", "advance_state")
    graph.add_edge("skip_verify_step", "advance_state")
    graph.add_conditional_edges(
        "advance_state", route_after_advance, {"load_step": "load_step", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)
    return graph.compile()


code_harness_graph = build_code_harness_graph()
