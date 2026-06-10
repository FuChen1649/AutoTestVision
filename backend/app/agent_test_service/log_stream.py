"""Per-run 实时日志流。

后端在 analyzer / verifier 内部的关键节点 emit 进度信息，
``stream_run`` 把队列内容和 harness 事件并发合流后推给前端。

设计要点：
- 日志只放在内存队列，不写库（避免高频 LLM 调用刷爆 DB）；
- 通过 ``contextvars`` 把 ``run_id`` / ``step_order`` 透传给底层组件，
  这样 analyzer / verifier 不需要改函数签名也能找到正确的队列；
- 实时日志 ``id`` 取负值（每个 run 内单调递减），前端凭符号区分实时 / 持久。
"""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timezone

from app.agent_test_service.schemas import AgentLogItem

_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_current_run_id", default=None
)
_current_step_order: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "agent_current_step_order", default=None
)

_queues: dict[str, asyncio.Queue[AgentLogItem]] = {}
_id_counter: dict[str, int] = {}


def set_context(run_id: str | None, step_order: int | None) -> None:
    _current_run_id.set(run_id)
    _current_step_order.set(step_order)


def subscribe(run_id: str) -> asyncio.Queue[AgentLogItem]:
    queue = _queues.get(run_id)
    if queue is None:
        queue = asyncio.Queue(maxsize=512)
        _queues[run_id] = queue
        _id_counter[run_id] = 0
    return queue


def release(run_id: str) -> None:
    _queues.pop(run_id, None)
    _id_counter.pop(run_id, None)


def emit(
    agent_type: str,
    message: str,
    *,
    step_order: int | None = None,
    detail: dict | None = None,
) -> None:
    """从任意协程发布一条实时日志；找不到 run 上下文 / 无订阅者时静默丢弃。"""
    run_id = _current_run_id.get()
    if not run_id:
        return
    queue = _queues.get(run_id)
    if queue is None:
        return

    _id_counter[run_id] = _id_counter.get(run_id, 0) - 1
    log = AgentLogItem(
        id=_id_counter[run_id],
        step_order=step_order if step_order is not None else _current_step_order.get(),
        agent_type=agent_type,
        message=message,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )
    try:
        queue.put_nowait(log)
    except asyncio.QueueFull:
        pass
