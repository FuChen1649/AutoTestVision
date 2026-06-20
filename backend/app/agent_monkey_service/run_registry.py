from __future__ import annotations

import asyncio


class MonkeyRunRegistry:
    def __init__(self) -> None:
        self._cancel: set[str] = set()
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, session_uuid: str) -> None:
        self._cancel.discard(session_uuid)

    def request_cancel(self, session_uuid: str) -> None:
        self._cancel.add(session_uuid)
        task = self._tasks.get(session_uuid)
        if task and not task.done():
            task.cancel()

    def is_cancel_requested(self, session_uuid: str) -> bool:
        return session_uuid in self._cancel

    def set_task(self, session_uuid: str, task: asyncio.Task) -> None:
        self._tasks[session_uuid] = task

    def clear(self, session_uuid: str) -> None:
        self._cancel.discard(session_uuid)
        self._tasks.pop(session_uuid, None)


monkey_run_registry = MonkeyRunRegistry()
