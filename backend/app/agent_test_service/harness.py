"""LangGraph Harness：Observe -> Analyze -> Act -> Verify -> Advance 闭环。"""

from langgraph.graph import END, StateGraph

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.action_executor import action_executor
from app.agent_test_service.image_annotation import annotate_before_image
from app.agent_test_service.intent_analyzer import intent_analyzer
from app.agent_test_service.schemas import AnalyzeIntentRequest, StepExecutionRecord
from app.agent_test_service.state import HarnessAgentState, utc_now
from app.agent_test_service.step_verifier import step_verifier

logger = get_agent_logger()


def _current_step(state: HarnessAgentState) -> StepExecutionRecord:
    index = state.get("current_step_index", 0)
    return state["steps"][index]


def _update_step(state: HarnessAgentState, record: StepExecutionRecord) -> list[StepExecutionRecord]:
    return [record]


async def load_step_node(state: HarnessAgentState) -> HarnessAgentState:
    index = state.get("current_step_index", 0)
    logger.info("[harness:load_step] run=%s step_index=%d", state.get("run_id"), index)
    if index >= state.get("total_steps", 0):
        return {
            "status": "completed",
            "should_continue": False,
            "updated_at": utc_now(),
        }

    step = state["steps"][index]

    return {
        "status": "running",
        "current_description": step.description,
        "current_step_type": step.step_type,
        "current_reference_image": step.reference_image,
        "current_reference_x": step.reference_x,
        "current_reference_y": step.reference_y,
        "current_reference_width": step.reference_width,
        "current_reference_height": step.reference_height,
        "should_continue": True,
        "updated_at": utc_now(),
    }


async def capture_before_node(state: HarnessAgentState) -> HarnessAgentState:
    logger.info("[harness:capture_before] run=%s serial=%s", state.get("run_id"), state.get("serial"))
    image, width, height = await action_executor.capture_screen(state.get("serial"))
    step = _current_step(state)
    step.status = "running"
    step.before_image = image
    return {
        "before_image": image,
        "screen_width": width,
        "screen_height": height,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def analyze_intent_node(state: HarnessAgentState) -> HarnessAgentState:
    step = _current_step(state)
    logger.info("[harness:analyze_intent] run=%s desc=%s", state.get("run_id"), step.description[:80])
    request = AnalyzeIntentRequest(
        step_description=state.get("current_description", step.description),
        screen_image=state.get("before_image") or "",
        screen_width=state.get("screen_width", 0),
        screen_height=state.get("screen_height", 0),
        reference_image=state.get("current_reference_image"),
        reference_x=state.get("current_reference_x"),
        reference_y=state.get("current_reference_y"),
        reference_width=state.get("current_reference_width"),
        reference_height=state.get("current_reference_height"),
    )
    intent = await intent_analyzer.analyze(request, provider=state.get("llm_provider"))
    logger.info(
        "[harness:analyze_intent] run=%s provider=%s action=%s confidence=%.2f",
        state.get("run_id"),
        state.get("llm_provider"),
        intent.action,
        intent.confidence,
    )
    step.intent = intent
    if step.before_image:
        step.before_image_annotated = annotate_before_image(step.before_image, intent)
    return {
        "intent": intent,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def execute_action_node(state: HarnessAgentState) -> HarnessAgentState:
    intent = state.get("intent")
    if intent is None:
        logger.error("[harness:execute_action] run=%s 缺少意图分析结果", state.get("run_id"))
        raise RuntimeError("缺少意图分析结果")
    logger.info("[harness:execute_action] run=%s action=%s", state.get("run_id"), intent.action)

    device_width, device_height = state.get("screen_width", 0), state.get("screen_height", 0)
    mapped = action_executor.map_coordinates(
        intent,
        model_width=device_width,
        model_height=device_height,
        device_width=device_width,
        device_height=device_height,
    )
    executed = await action_executor.execute(mapped, serial=state.get("serial"))
    step = _current_step(state)
    step.intent = executed
    return {
        "intent": executed,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def capture_after_node(state: HarnessAgentState) -> HarnessAgentState:
    logger.info("[harness:capture_after] run=%s", state.get("run_id"))
    image, _, _ = await action_executor.capture_screen(state.get("serial"))
    step = _current_step(state)
    step.after_image = image
    return {
        "after_image": image,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def verify_step_node(state: HarnessAgentState) -> HarnessAgentState:
    step = _current_step(state)
    intent = state.get("intent")
    before_image = state.get("before_image")
    after_image = state.get("after_image")
    logger.info("[harness:verify_step] run=%s step=%d", state.get("run_id"), step.step_order)
    if intent is None or not before_image or not after_image:
        logger.error("[harness:verify_step] run=%s 验证缺少截图或意图", state.get("run_id"))
        raise RuntimeError("验证缺少截图或意图")

    verification = await step_verifier.verify(
        step_description=step.description,
        intent=intent,
        before_image=before_image,
        after_image=after_image,
        provider=state.get("llm_provider"),
    )
    step.verification = verification
    step.status = "success" if verification.success else "failed"
    if not verification.success:
        step.error = verification.reasoning
    logger.info(
        "[harness:verify_step] run=%s success=%s confidence=%.2f",
        state.get("run_id"),
        verification.success,
        verification.confidence,
    )

    return {
        "verification": verification,
        "steps": _update_step(state, step),
        "updated_at": utc_now(),
    }


async def advance_state_node(state: HarnessAgentState) -> HarnessAgentState:
    step = _current_step(state)
    verification = state.get("verification")
    logger.info(
        "[harness:advance_state] run=%s retry=%d success=%s",
        state.get("run_id"),
        state.get("retry_count", 0),
        verification.success if verification else None,
    )
    if verification and verification.success:
        next_index = state.get("current_step_index", 0) + 1
        finished = next_index >= state.get("total_steps", 0)
        return {
            "current_step_index": next_index,
            "retry_count": 0,
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
            "error": step.error or "步骤验证失败且超过最大重试次数",
            "steps": _update_step(state, step),
            "updated_at": utc_now(),
        }

    return {
        "retry_count": retry_count,
        "should_continue": True,
        "updated_at": utc_now(),
    }


def route_after_advance(state: HarnessAgentState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    if state.get("should_continue"):
        return "load_step"
    return "finalize"


async def finalize_node(state: HarnessAgentState) -> HarnessAgentState:
    status = state.get("status", "running")
    if status == "running":
        status = "completed"
    logger.info("[harness:finalize] run=%s status=%s error=%s", state.get("run_id"), status, state.get("error"))
    return {"status": status, "updated_at": utc_now()}


def build_harness_graph():
    graph = StateGraph(HarnessAgentState)

    graph.add_node("load_step", load_step_node)
    graph.add_node("capture_before", capture_before_node)
    graph.add_node("analyze_intent", analyze_intent_node)
    graph.add_node("execute_action", execute_action_node)
    graph.add_node("capture_after", capture_after_node)
    graph.add_node("verify_step", verify_step_node)
    graph.add_node("advance_state", advance_state_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("load_step")
    graph.add_edge("load_step", "capture_before")
    graph.add_edge("capture_before", "analyze_intent")
    graph.add_edge("analyze_intent", "execute_action")
    graph.add_edge("execute_action", "capture_after")
    graph.add_edge("capture_after", "verify_step")
    graph.add_edge("verify_step", "advance_state")
    graph.add_conditional_edges(
        "advance_state",
        route_after_advance,
        {
            "load_step": "load_step",
            "finalize": "finalize",
        },
    )
    graph.add_edge("finalize", END)

    return graph.compile()


harness_graph = build_harness_graph()
