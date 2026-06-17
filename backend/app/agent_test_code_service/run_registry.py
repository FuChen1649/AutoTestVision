from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

_active: dict[str, "CodeRunRuntime"] = {}


@dataclass
class CodeRunRuntime:
    cancel_requested: bool = False
    harness_task: asyncio.Task | None = field(default=None, repr=False)


def register(run_uuid: str) -> CodeRunRuntime:
    runtime = _active.get(run_uuid)
    if runtime is None:
        runtime = CodeRunRuntime()
        _active[run_uuid] = runtime
    return runtime


def release(run_uuid: str) -> None:
    _active.pop(run_uuid, None)


def request_cancel(run_uuid: str) -> None:
    runtime = register(run_uuid)
    runtime.cancel_requested = True
    task = runtime.harness_task
    if task and not task.done():
        task.cancel()


def is_cancel_requested(run_uuid: str) -> bool:
    runtime = _active.get(run_uuid)
    return bool(runtime and runtime.cancel_requested)


def set_harness_task(run_uuid: str, task: asyncio.Task) -> None:
    register(run_uuid).harness_task = task
