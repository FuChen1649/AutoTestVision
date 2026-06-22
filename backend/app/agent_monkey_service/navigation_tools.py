from __future__ import annotations

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.repository import monkey_repository
from app.agent_monkey_service.schemas import BBox, Center
from app.config import settings
from app.models.monkey import MonkeyNode, MonkeyScreenAction, MonkeySession
from app.services.adb import adb_service


class MonkeyNavigationTools:
    async def replay_script(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        script: list[dict],
        nodes_by_uuid: dict[str, MonkeyNode],
        extra_wait_after_last_ms: int = 0,
    ) -> dict:
        if not script:
            return {"result": "ok", "message": "无需回放"}
        for index, item in enumerate(script):
            tool_name = str(item.get("tool") or "").strip().lower()
            args = dict(item.get("args") or {})
            await self._run_tool(
                db,
                session,
                step_index=step_index,
                tool_name=tool_name,
                args=args,
                nodes_by_uuid=nodes_by_uuid,
                record=True,
            )
            if index == len(script) - 1 and extra_wait_after_last_ms > 0:
                await asyncio.sleep(extra_wait_after_last_ms / 1000)
        return {"result": "ok", "message": f"已回放 {len(script)} 步路径"}

    async def execute_screen_action(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        action: MonkeyScreenAction,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> dict:
        if not action.center_json:
            raise RuntimeError(f"操作 {action.action_no} 缺少坐标")
        center = Center.model_validate_json(action.center_json)
        serial = session.serial
        action_type = (action.action_type or "tap").strip().lower()

        if action_type == "tap":
            await adb_service.tap(center.x, center.y, serial=serial)
            message = f"点击 #{action.action_no} {action.element_title}"
        elif action_type == "long_press":
            await adb_service.long_press(center.x, center.y, duration_ms=800, serial=serial)
            message = f"长按 #{action.action_no} {action.element_title}"
        elif action_type == "swipe":
            if not action.swipe_to_json:
                raise RuntimeError(f"滑动操作 {action.action_no} 缺少终点")
            end = BBox.model_validate_json(action.swipe_to_json)
            x2 = end.x + end.w // 2
            y2 = end.y + end.h // 2
            await adb_service.swipe(center.x, center.y, x2, y2, serial=serial)
            message = f"滑动 #{action.action_no} {action.element_title}"
        else:
            await adb_service.tap(center.x, center.y, serial=serial)
            message = f"点击 #{action.action_no} {action.element_title}"

        await self._wait()
        await monkey_repository.add_action(
            db,
            session,
            step_index=step_index,
            tool_name=action_type,
            x=center.x,
            y=center.y,
            title=f"#{action.action_no} {action.element_title}",
            result="ok",
            detail={"action_uuid": action.action_uuid, "screen_node_uuid": action.screen_node_uuid},
        )
        return {"result": "ok", "message": message, "action_uuid": action.action_uuid}

    async def execute(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        tool_name: str,
        args: dict,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> dict:
        return await self._run_tool(
            db,
            session,
            step_index=step_index,
            tool_name=tool_name,
            args=args,
            nodes_by_uuid=nodes_by_uuid,
            record=True,
        )

    async def _run_tool(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        tool_name: str,
        args: dict,
        nodes_by_uuid: dict[str, MonkeyNode],
        record: bool,
    ) -> dict:
        serial = session.serial
        tool_name = (tool_name or "stop").strip().lower()
        args = args or {}

        if tool_name == "stop":
            return {"result": "stop", "message": "模型请求停止"}

        if tool_name == "go_home":
            await asyncio.to_thread(adb_service.go_home, serial)
            await asyncio.to_thread(adb_service.press_home_key, serial, times=1)
            await self._wait()
            if record:
                await monkey_repository.add_action(
                    db, session, step_index=step_index, tool_name=tool_name, title="Home", result="ok"
                )
            return {"result": "ok", "message": "已返回主屏幕"}

        if tool_name == "go_back":
            await asyncio.to_thread(adb_service.press_back_key, serial, times=1)
            await self._wait()
            if record:
                await monkey_repository.add_action(
                    db, session, step_index=step_index, tool_name=tool_name, title="Back", result="ok"
                )
            return {"result": "ok", "message": "已按返回键"}

        if tool_name == "tap_node":
            node_uuid = args.get("node_uuid")
            if not node_uuid or node_uuid not in nodes_by_uuid:
                raise RuntimeError("tap_node 缺少有效 node_uuid")
            return await self._tap_node(
                db, session, step_index, nodes_by_uuid[node_uuid], tool_name, record=record
            )

        if tool_name == "navigate_to_node":
            node_uuid = args.get("node_uuid")
            if not node_uuid or node_uuid not in nodes_by_uuid:
                raise RuntimeError("navigate_to_node 缺少有效 node_uuid")
            path = self._build_path(nodes_by_uuid, node_uuid)
            await asyncio.to_thread(adb_service.go_home, serial)
            await asyncio.to_thread(adb_service.press_home_key, serial, times=1)
            await self._wait()
            for node in path:
                if node.node_type == "root":
                    continue
                await self._tap_node(db, session, step_index, node, "navigate_to_node", record=record)
            return {
                "result": "ok",
                "message": f"已导航到 {nodes_by_uuid[node_uuid].title}",
                "path": [n.title for n in path],
            }

        if tool_name in {"tap", "tap_coordinates"}:
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))
            pixel_x, pixel_y = self._to_pixel(x, y, args, nodes_by_uuid)
            await adb_service.tap(pixel_x, pixel_y, serial=serial)
            await self._wait()
            if record:
                await monkey_repository.add_action(
                    db,
                    session,
                    step_index=step_index,
                    tool_name="tap",
                    x=pixel_x,
                    y=pixel_y,
                    title=args.get("title"),
                    result="ok",
                )
            return {"result": "ok", "message": f"点击 ({pixel_x},{pixel_y})", "x": pixel_x, "y": pixel_y}

        if tool_name == "long_press":
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))
            duration_ms = int(args.get("duration_ms", 800))
            pixel_x, pixel_y = self._to_pixel(x, y, args, nodes_by_uuid)
            await adb_service.long_press(pixel_x, pixel_y, duration_ms=duration_ms, serial=serial)
            await self._wait()
            if record:
                await monkey_repository.add_action(
                    db,
                    session,
                    step_index=step_index,
                    tool_name=tool_name,
                    x=pixel_x,
                    y=pixel_y,
                    title=args.get("title"),
                    result="ok",
                )
            return {"result": "ok", "message": f"长按 ({pixel_x},{pixel_y})"}

        if tool_name == "swipe":
            x1 = int(args.get("x1", args.get("x", 0)))
            y1 = int(args.get("y1", args.get("y", 0)))
            x2 = int(args.get("x2", 0))
            y2 = int(args.get("y2", 0))
            px1, py1 = self._to_pixel(x1, y1, args, nodes_by_uuid)
            px2, py2 = self._to_pixel(x2, y2, args, nodes_by_uuid)
            await adb_service.swipe(px1, py1, px2, py2, serial=serial)
            await self._wait()
            if record:
                await monkey_repository.add_action(
                    db,
                    session,
                    step_index=step_index,
                    tool_name=tool_name,
                    title=args.get("title"),
                    result="ok",
                    detail={"x1": px1, "y1": py1, "x2": px2, "y2": py2},
                )
            return {"result": "ok", "message": f"滑动 ({px1},{py1})→({px2},{py2})"}

        raise RuntimeError(f"未知工具: {tool_name}")

    async def _tap_node(
        self,
        db: AsyncSession,
        session: MonkeySession,
        step_index: int,
        node: MonkeyNode,
        tool_name: str,
        *,
        record: bool,
    ) -> dict:
        center = self._node_center(node)
        if not center:
            raise RuntimeError(f"节点 {node.title} 无有效坐标")
        await adb_service.tap(center.x, center.y, serial=session.serial)
        await self._wait()
        node.status = "explored"
        if record:
            await monkey_repository.add_action(
                db,
                session,
                step_index=step_index,
                tool_name=tool_name,
                node_uuid=node.node_uuid,
                x=center.x,
                y=center.y,
                title=node.title,
                result="ok",
            )
        return {"result": "ok", "message": f"点击节点 {node.title}", "node_uuid": node.node_uuid}

    def action_to_replay_step(self, action: MonkeyScreenAction) -> dict:
        if not action.center_json:
            return {"tool": "tap", "args": {}}
        center = Center.model_validate_json(action.center_json)
        action_type = (action.action_type or "tap").strip().lower()
        if action_type == "long_press":
            return {"tool": "long_press", "args": {"x": center.x, "y": center.y, "duration_ms": 800}}
        if action_type == "swipe" and action.swipe_to_json:
            end = BBox.model_validate_json(action.swipe_to_json)
            return {
                "tool": "swipe",
                "args": {
                    "x1": center.x,
                    "y1": center.y,
                    "x2": end.x + end.w // 2,
                    "y2": end.y + end.h // 2,
                },
            }
        return {"tool": "tap", "args": {"x": center.x, "y": center.y, "title": action.element_title}}

    def _node_center(self, node: MonkeyNode) -> Center | None:
        if node.center_json:
            return Center.model_validate_json(node.center_json)
        if node.bbox_json:
            bbox = BBox.model_validate_json(node.bbox_json)
            return Center(x=bbox.x + bbox.w // 2, y=bbox.y + bbox.h // 2)
        return None

    def _to_pixel(self, x: int, y: int, args: dict, nodes_by_uuid: dict[str, MonkeyNode]) -> tuple[int, int]:
        node_uuid = args.get("node_uuid")
        if node_uuid and node_uuid in nodes_by_uuid:
            center = self._node_center(nodes_by_uuid[node_uuid])
            if center:
                return center.x, center.y
        sw = int(args.get("screen_width") or 1080)
        sh = int(args.get("screen_height") or 1920)
        if max(x, y) <= 1000:
            return round(x / 1000 * sw), round(y / 1000 * sh)
        return x, y

    def _build_path(self, nodes_by_uuid: dict[str, MonkeyNode], target_uuid: str) -> list[MonkeyNode]:
        path: list[MonkeyNode] = []
        current = nodes_by_uuid.get(target_uuid)
        while current:
            path.append(current)
            if not current.parent_node_uuid:
                break
            current = nodes_by_uuid.get(current.parent_node_uuid)
        path.reverse()
        return path

    async def _wait(self) -> None:
        delay_ms = settings.agent_after_capture_delay_ms
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)


monkey_navigation_tools = MonkeyNavigationTools()
