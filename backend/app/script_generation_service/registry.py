import asyncio
from dataclasses import dataclass, field


@dataclass
class ScriptGenRuntime:
    task_uuid: str
    cancelled: bool = False
    assertion_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    assertion_results: dict[int, bool] = field(default_factory=dict)
    assertion_events: dict[int, asyncio.Event] = field(default_factory=dict)
    harness_task: asyncio.Task | None = field(default=None, repr=False)


class ScriptGenRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, ScriptGenRuntime] = {}

    def register(self, task_uuid: str) -> ScriptGenRuntime:
        runtime = ScriptGenRuntime(task_uuid=task_uuid)
        self._runtimes[task_uuid] = runtime
        return runtime

    def get(self, task_uuid: str) -> ScriptGenRuntime | None:
        return self._runtimes.get(task_uuid)

    def cancel(self, task_uuid: str) -> None:
        runtime = self._runtimes.get(task_uuid)
        if not runtime:
            return
        runtime.cancelled = True
        if runtime.harness_task and not runtime.harness_task.done():
            runtime.harness_task.cancel()

    def remove(self, task_uuid: str) -> None:
        self._runtimes.pop(task_uuid, None)


script_gen_registry = ScriptGenRegistry()
