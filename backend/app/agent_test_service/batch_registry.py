"""批量执行运行时状态：跟踪当前 Case 与中止请求。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BatchRuntime:
    current_run_uuid: str | None = None
    current_case_order: int | None = None
    cancel_requested: bool = False


_active: dict[str, BatchRuntime] = {}


def register(batch_uuid: str) -> BatchRuntime:
    runtime = _active.get(batch_uuid)
    if runtime is None:
        runtime = BatchRuntime()
        _active[batch_uuid] = runtime
    return runtime


def release(batch_uuid: str) -> None:
    _active.pop(batch_uuid, None)


def set_current_run(batch_uuid: str, run_uuid: str | None, case_order: int | None = None) -> None:
    runtime = register(batch_uuid)
    runtime.current_run_uuid = run_uuid
    runtime.current_case_order = case_order


def request_cancel(batch_uuid: str) -> BatchRuntime | None:
    runtime = _active.get(batch_uuid)
    if runtime is None:
        runtime = BatchRuntime(cancel_requested=True)
        _active[batch_uuid] = runtime
    else:
        runtime.cancel_requested = True
    return runtime


def is_cancel_requested(batch_uuid: str) -> bool:
    runtime = _active.get(batch_uuid)
    return bool(runtime and runtime.cancel_requested)


def current_run_uuid(batch_uuid: str) -> str | None:
    runtime = _active.get(batch_uuid)
    return runtime.current_run_uuid if runtime else None


def current_case_order(batch_uuid: str) -> int | None:
    runtime = _active.get(batch_uuid)
    return runtime.current_case_order if runtime else None
