from __future__ import annotations

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.repository import monkey_repository
from app.agent_monkey_service.schemas import BBox, Center
from app.config import settings
from app.models.monkey import MonkeyNode, MonkeySession
from app.services.adb import adb_service


class MonkeyNavigationTools:
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
        serial = session.serial
        tool_name = (tool_name or "stop").strip().lower()
        args = args or {}

        if tool_name == "stop":
            return {"result": "stop", "message": "模型请求停止"}

        if tool_name == "go_home":
            await asyncio.to_thread(adb_service.go_home, serial)
            await asyncio.to_thread(adb_service.press_home_key, serial, times=1)
            await self._wait()
            await monkey_repository.add_action(
                db, session, step_index=step_index, tool_name=tool_name, title="Home", result="ok"
            )
            return {"result": "ok", "message": "已返回主屏幕"}

        if tool_name == "go_back":
            await asyncio.to_thread(adb_service.press_back_key, serial, times=1)
            await self._wait()
            await monkey_repository.add_action(
                db, session, step_index=step_index, tool_name=tool_name, title="Back", result="ok"
            )
            return {"result": "ok", "message": "已按返回键"}

        if tool_name == "tap_node":
            node_uuid = args.get("node_uuid")
            if not node_uuid or node_uuid not in nodes_by_uuid:
                raise RuntimeError("tap_node 缺少有效 node_uuid")
            return await self._tap_node(db, session, step_index, nodes_by_uuid[node_uuid], tool_name)

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
                await self._tap_node(db, session, step_index, node, "navigate_to_node")
            return {"result": "ok", "message": f"已导航到 {nodes_by_uuid[node_uuid].title}", "path": [n.title for n in path]}

        if tool_name == "tap_coordinates":
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))
            pixel_x, pixel_y = self._to_pixel(x, y, args, nodes_by_uuid)
            await adb_service.tap(pixel_x, pixel_y, serial=serial)
            await self._wait()
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
            return {"result": "ok", "message": f"点击 ({pixel_x},{pixel_y})", "x": pixel_x, "y": pixel_y}

        raise RuntimeError(f"未知工具: {tool_name}")

    async def _tap_node(
        self,
        db: AsyncSession,
        session: MonkeySession,
        step_index: int,
        node: MonkeyNode,
        tool_name: str,
    ) -> dict:
        center = self._node_center(node)
        if not center:
            raise RuntimeError(f"节点 {node.title} 无有效坐标")
        await adb_service.tap(center.x, center.y, serial=session.serial)
        await self._wait()
        node.status = "explored"
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
