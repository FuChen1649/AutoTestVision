from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.repository import (
    compute_screen_fingerprint,
    decode_data_url,
    monkey_repository,
)
from app.agent_monkey_service.schemas import BBox
from app.agent_monkey_service.screenshot_utils import (
    annotate_bbox_on_image,
    center_from_bbox,
    normalized_bbox_to_pixels,
)
from app.models.monkey import MonkeyNode, MonkeySession


class MonkeyTreeManager:
    async def bootstrap_home(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[MonkeyNode, MonkeyNode]:
        image_bytes = decode_data_url(screenshot_data_url)
        fingerprint = compute_screen_fingerprint(image_bytes)
        shot_name = monkey_repository.save_screenshot_bytes(
            session.session_uuid, "step_0_home.png", image_bytes
        )
        root = await monkey_repository.add_node(
            db,
            session,
            node_type="root",
            title=f"探索 · {session.target_app_name}",
            parent_node_uuid=None,
            screenshot_path=shot_name,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=fingerprint,
            status="explored",
            depth=0,
            confidence=1.0,
            description="会话根节点",
        )
        home = await monkey_repository.add_node(
            db,
            session,
            node_type="screen",
            title="主屏幕 · Home",
            parent_node_uuid=root.node_uuid,
            screenshot_path=shot_name,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=fingerprint,
            status="explored",
            depth=1,
            confidence=1.0,
            description="探索起点",
        )
        session.current_node_uuid = home.node_uuid
        session.navigation_stack_json = json.dumps([home.node_uuid])
        await monkey_repository.update_session(db, session)
        return root, home

    async def merge_discovered_nodes(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        parent_node: MonkeyNode,
        discovered: list[dict],
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        screen_fingerprint: str,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> list[MonkeyNode]:
        created: list[MonkeyNode] = []
        image_bytes = decode_data_url(screenshot_data_url)
        for item in discovered[:12]:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            if self._is_duplicate(nodes_by_uuid.values(), parent_node.node_uuid, title, item):
                continue
            bbox_norm = item.get("bbox") or {}
            bbox = normalized_bbox_to_pixels(bbox_norm, screen_width, screen_height)
            center = center_from_bbox(bbox)
            annotated = annotate_bbox_on_image(image_bytes, bbox, center, title)
            shot_name = monkey_repository.save_screenshot_bytes(
                session.session_uuid,
                f"node_{uuid.uuid4().hex[:8]}.png",
                image_bytes,
            )
            annotated_name = monkey_repository.save_screenshot_bytes(
                session.session_uuid,
                f"node_{uuid.uuid4().hex[:8]}_annotated.png",
                annotated,
            )
            node_type = str(item.get("node_type") or "element")
            if node_type not in {"app", "element", "screen", "container"}:
                node_type = "element"
            node = await monkey_repository.add_node(
                db,
                session,
                parent_node_uuid=parent_node.node_uuid,
                node_type=node_type,
                title=title,
                description=str(item.get("reasoning") or ""),
                screenshot_path=shot_name,
                annotated_screenshot_path=annotated_name,
                bbox=bbox,
                center=center,
                screen_width=screen_width,
                screen_height=screen_height,
                screen_fingerprint=screen_fingerprint,
                status="discovered",
                depth=parent_node.depth + 1,
                confidence=float(item.get("confidence") or 0.5),
                metadata={"client_id": item.get("client_id"), "clickable": item.get("clickable", True)},
            )
            nodes_by_uuid[node.node_uuid] = node
            created.append(node)
        return created

    def tree_for_prompt(self, session: MonkeySession, nodes_by_uuid: dict[str, MonkeyNode]) -> dict:
        nodes = []
        for node in sorted(nodes_by_uuid.values(), key=lambda item: (item.depth, item.id)):
            bbox = json.loads(node.bbox_json) if node.bbox_json else None
            center = json.loads(node.center_json) if node.center_json else None
            nodes.append(
                {
                    "node_uuid": node.node_uuid,
                    "parent_node_uuid": node.parent_node_uuid,
                    "node_type": node.node_type,
                    "title": node.title,
                    "status": node.status,
                    "depth": node.depth,
                    "bbox": bbox,
                    "center": center,
                }
            )
        return {
            "target_app_name": session.target_app_name,
            "current_node_uuid": session.current_node_uuid,
            "nodes": nodes,
        }

    def _is_duplicate(
        self,
        nodes: list[MonkeyNode],
        parent_uuid: str,
        title: str,
        item: dict,
    ) -> bool:
        for node in nodes:
            if node.parent_node_uuid != parent_uuid:
                continue
            if node.title == title:
                return True
            if node.bbox_json and item.get("bbox"):
                existing = BBox.model_validate_json(node.bbox_json)
                incoming = normalized_bbox_to_pixels(item["bbox"], node.screen_width or 1080, node.screen_height or 1920)
                if self._iou(existing, incoming) > 0.65:
                    return True
        return False

    def _iou(self, a: BBox, b: BBox) -> float:
        x1 = max(a.x, b.x)
        y1 = max(a.y, b.y)
        x2 = min(a.x + a.w, b.x + b.w)
        y2 = min(a.y + a.h, b.y + b.h)
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        union = a.w * a.h + b.w * b.h - inter
        return inter / union if union > 0 else 0.0


monkey_tree_manager = MonkeyTreeManager()
