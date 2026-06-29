from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.navigation_tools import monkey_navigation_tools
from app.agent_monkey_service.repository import (
    compute_screen_fingerprint,
    decode_data_url,
    monkey_repository,
)
from app.agent_monkey_service.schemas import BBox, Center
from app.agent_monkey_service.screenshot_utils import (
    annotate_screen_with_numbers,
    bbox_overlap_ratio,
    center_from_bbox,
    normalized_bbox_to_pixels,
    parse_candidate_bbox,
    perceptual_similar,
    titles_similar,
)
from app.agent_test_service.agent_logger import get_agent_logger
from app.models.monkey import MonkeyNode, MonkeyScreenAction, MonkeySession
from app.services.adb import adb_service

logger = get_agent_logger()


class MonkeyScreenManager:
    def load_navigation_state(self, session: MonkeySession) -> dict[str, Any]:
        raw = session.navigation_stack_json
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"focus_screen_uuid": raw} if isinstance(raw, str) else {}
        if isinstance(data, list):
            return {"focus_screen_uuid": data[-1] if data else None, "legacy_stack": data}
        return data

    def save_focus_screen(self, session: MonkeySession, focus_screen_uuid: str) -> None:
        state = self.load_navigation_state(session)
        state["focus_screen_uuid"] = focus_screen_uuid
        session.navigation_stack_json = json.dumps(state, ensure_ascii=False)

    def get_focus_screen_uuid(self, session: MonkeySession) -> str | None:
        state = self.load_navigation_state(session)
        stack = state.get("explore_stack") or []
        if stack:
            return stack[-1]
        return state.get("focus_screen_uuid") or session.current_node_uuid

    def get_explore_stack(self, session: MonkeySession) -> list[str]:
        state = self.load_navigation_state(session)
        return list(state.get("explore_stack") or [])

    def save_explore_stack(self, session: MonkeySession, stack: list[str]) -> None:
        state = self.load_navigation_state(session)
        state["explore_stack"] = stack
        if stack:
            state["focus_screen_uuid"] = stack[-1]
        session.navigation_stack_json = json.dumps(state, ensure_ascii=False)

    def push_explore_stack(self, session: MonkeySession, screen_uuid: str) -> None:
        stack = self.get_explore_stack(session)
        if stack and stack[-1] == screen_uuid:
            self.save_focus_screen(session, screen_uuid)
            return
        stack.append(screen_uuid)
        self.save_explore_stack(session, stack)

    def pop_explore_stack(self, session: MonkeySession) -> str | None:
        stack = self.get_explore_stack(session)
        if len(stack) <= 1:
            self.save_explore_stack(session, stack[:1] if stack else [])
            return stack[0] if stack else None
        stack.pop()
        self.save_explore_stack(session, stack)
        return stack[-1]

    def screen_metadata(self, screen: MonkeyNode) -> dict[str, Any]:
        if not screen.metadata_json:
            return {}
        try:
            return json.loads(screen.metadata_json)
        except json.JSONDecodeError:
            return {}

    def is_discovery_done(self, screen: MonkeyNode) -> bool:
        return bool(self.screen_metadata(screen).get("discovery_done"))

    def mark_discovery_done(self, screen: MonkeyNode) -> None:
        meta = self.screen_metadata(screen)
        meta["discovery_done"] = True
        screen.metadata_json = json.dumps(meta, ensure_ascii=False)

    def reset_discovery(self, screen: MonkeyNode) -> None:
        """允许重新调用模型定位元素（如主屏启动应用坐标不准）。"""
        meta = self.screen_metadata(screen)
        meta["discovery_done"] = False
        screen.metadata_json = json.dumps(meta, ensure_ascii=False)

    def is_screenshot_locked(self, screen: MonkeyNode) -> bool:
        return bool(self.screen_metadata(screen).get("screenshot_locked"))

    def lock_screen_screenshot(self, screen: MonkeyNode) -> None:
        meta = self.screen_metadata(screen)
        meta["screenshot_locked"] = True
        meta["discovery_done"] = True
        screen.metadata_json = json.dumps(meta, ensure_ascii=False)

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
            session.session_uuid, "screen_0_home.png", image_bytes
        )
        root = await monkey_repository.add_node(
            db,
            session,
            node_type="root",
            title=f"探索 · {session.target_app_name}",
            parent_node_uuid=None,
            screenshot_path=shot_name,
            annotated_screenshot_path=shot_name,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=fingerprint,
            status="explored",
            depth=0,
            confidence=1.0,
            description="会话根",
            metadata={"replay_script": []},
        )
        home = await monkey_repository.add_node(
            db,
            session,
            node_type="screen",
            title="主屏幕 · Home",
            parent_node_uuid=root.node_uuid,
            screenshot_path=shot_name,
            annotated_screenshot_path=shot_name,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=fingerprint,
            status="exploring",
            depth=1,
            confidence=1.0,
            description="探索起点",
            metadata={"replay_script": [{"tool": "go_home", "args": {}}], "screenshot_locked": True},
        )
        session.current_node_uuid = home.node_uuid
        self.save_explore_stack(session, [home.node_uuid])
        await monkey_repository.update_session(db, session)
        return root, home

    def find_screen_by_triggered_action(
        self, nodes_by_uuid: dict[str, MonkeyNode], action_uuid: str
    ) -> MonkeyNode | None:
        for node in nodes_by_uuid.values():
            if node.node_type != "screen":
                continue
            meta = self.screen_metadata(node)
            if meta.get("triggered_by_action_uuid") == action_uuid:
                return node
        return None

    def find_screen_by_fingerprint(
        self, nodes_by_uuid: dict[str, MonkeyNode], fingerprint: str
    ) -> MonkeyNode | None:
        for node in nodes_by_uuid.values():
            if node.node_type == "screen" and node.screen_fingerprint == fingerprint:
                return node
        return None

    def find_state_by_fingerprint(
        self,
        nodes_by_uuid: dict[str, MonkeyNode],
        fingerprint: str | None,
        *,
        exclude_uuid: str | None = None,
        threshold: int = 8,
    ) -> MonkeyNode | None:
        """用感知指纹（汉明距离）在已发现屏幕中找“同一页面”，找最相近的一个。"""
        if not fingerprint:
            return None
        best: MonkeyNode | None = None
        best_dist = threshold + 1
        from app.agent_monkey_service.screenshot_utils import hamming_distance

        for node in nodes_by_uuid.values():
            if node.node_type != "screen" or node.node_uuid == exclude_uuid:
                continue
            if not node.screen_fingerprint:
                continue
            dist = hamming_distance(fingerprint, node.screen_fingerprint)
            if dist <= threshold and dist < best_dist:
                best, best_dist = node, dist
        return best

    def known_screen_titles(self, nodes_by_uuid: dict[str, MonkeyNode]) -> list[str]:
        return [
            n.title
            for n in nodes_by_uuid.values()
            if n.node_type == "screen" and self.is_discovery_done(n)
        ]

    def fingerprints_match(self, a: str | None, b: str | None, *, threshold: int = 8) -> bool:
        return perceptual_similar(a, b, threshold=threshold)

    async def ensure_screen_node(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        fingerprint: str,
        screenshot_data_url: str,
        screen_width: int,
        screen_height: int,
        title: str,
        parent_node_uuid: str | None,
        depth: int,
        replay_script: list[dict[str, Any]],
        nodes_by_uuid: dict[str, MonkeyNode],
        triggered_by_action_uuid: str | None = None,
    ) -> MonkeyNode:
        if triggered_by_action_uuid:
            existing = self.find_screen_by_triggered_action(
                nodes_by_uuid, triggered_by_action_uuid
            )
            if existing:
                return existing

        image_bytes = decode_data_url(screenshot_data_url)
        shot_name = monkey_repository.save_screenshot_bytes(
            session.session_uuid,
            f"screen_{uuid.uuid4().hex[:8]}.png",
            image_bytes,
        )
        metadata: dict[str, Any] = {
            "replay_script": replay_script,
            "screenshot_locked": True,
        }
        if triggered_by_action_uuid:
            metadata["triggered_by_action_uuid"] = triggered_by_action_uuid
        node = await monkey_repository.add_node(
            db,
            session,
            node_type="screen",
            title=title,
            parent_node_uuid=parent_node_uuid,
            screenshot_path=shot_name,
            annotated_screenshot_path=shot_name,
            screen_width=screen_width,
            screen_height=screen_height,
            screen_fingerprint=fingerprint,
            status="discovered",
            depth=depth,
            confidence=1.0,
            description="探索中发现的新屏幕",
            metadata=metadata,
        )
        nodes_by_uuid[node.node_uuid] = node
        return node

    async def navigate_to_screen(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        target_screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> None:
        script = self.screen_replay_script(target_screen)
        if not script:
            raise RuntimeError(f"屏幕「{target_screen.title}」缺少回放路径，无法导航")
        await monkey_navigation_tools.replay_script(
            db,
            session,
            step_index=step_index,
            script=script,
            nodes_by_uuid=nodes_by_uuid,
        )

    def is_home_screen(self, screen: MonkeyNode) -> bool:
        script = self.screen_replay_script(screen)
        tools = {str(item.get("tool") or "").strip().lower() for item in script}
        return screen.depth <= 1 or tools <= {"go_home"}

    async def return_device_to_home(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
    ) -> tuple[bytes, int, int]:
        """父屏探索完后回到根（Home），不做严格指纹校验。"""
        serial = session.serial
        await asyncio.to_thread(adb_service.go_home, serial)
        await asyncio.to_thread(adb_service.press_home_key, serial, times=2)
        await asyncio.sleep(1.2)
        await monkey_repository.add_action(
            db, session, step_index=step_index, tool_name="go_home", title="返回 Home", result="ok"
        )
        image_bytes = await adb_service.capture_screen(serial=serial)
        width, height = adb_service.get_image_size(image_bytes)
        return image_bytes, width, height

    async def return_device_to_focus_screen(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        focus_screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> tuple[bytes, int, int]:
        """操作后回到当前焦点屏幕（父屏），继续在父屏执行剩余元素。"""
        if self.is_home_screen(focus_screen):
            return await self.return_device_to_home(db, session, step_index=step_index)
        return await self.ensure_device_at_screen(
            db,
            session,
            step_index=step_index,
            target_screen=focus_screen,
            nodes_by_uuid=nodes_by_uuid,
        )

    async def return_to_parent_via_back(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        parent_screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> tuple[bytes, int, int]:
        """回退到父屏：优先按一次系统返回键（快），校验指纹；不符再回退到整条重放。"""
        if self.is_home_screen(parent_screen):
            return await self.return_device_to_home(db, session, step_index=step_index)

        await asyncio.to_thread(adb_service.press_back_key, session.serial, times=1)
        await asyncio.sleep(1.2)
        await monkey_repository.add_action(
            db, session, step_index=step_index, tool_name="go_back", title="返回上一屏", result="ok"
        )
        image_bytes = await adb_service.capture_screen(serial=session.serial)
        width, height = adb_service.get_image_size(image_bytes)
        actual_fp = compute_screen_fingerprint(image_bytes)
        if not parent_screen.screen_fingerprint or self.fingerprints_match(
            actual_fp, parent_screen.screen_fingerprint
        ):
            parent_screen.status = "exploring"
            return image_bytes, width, height

        logger.info(
            "[monkey] back 键未回到「%s」，改用完整重放路径", parent_screen.title
        )
        return await self.ensure_device_at_screen(
            db,
            session,
            step_index=step_index,
            target_screen=parent_screen,
            nodes_by_uuid=nodes_by_uuid,
        )

    async def ensure_device_at_screen(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        target_screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> tuple[bytes, int, int]:
        """回放路径把真机导航到目标屏幕；Home 不校验指纹，子屏放宽校验。"""
        script = self.screen_replay_script(target_screen)
        if not script:
            raise RuntimeError(f"屏幕「{target_screen.title}」缺少回放路径")

        if self.is_home_screen(target_screen):
            await monkey_navigation_tools.replay_script(
                db,
                session,
                step_index=step_index,
                script=script,
                nodes_by_uuid=nodes_by_uuid,
            )
            await asyncio.sleep(1.0)
            image_bytes = await adb_service.capture_screen(serial=session.serial)
            width, height = adb_service.get_image_size(image_bytes)
            target_screen.status = "exploring"
            return image_bytes, width, height

        expected_fp = target_screen.screen_fingerprint
        parent_fp = self._parent_screen_fingerprint(target_screen, nodes_by_uuid)
        last_detail = ""
        for attempt in range(2):
            await monkey_navigation_tools.replay_script(
                db,
                session,
                step_index=step_index,
                script=script,
                nodes_by_uuid=nodes_by_uuid,
                extra_wait_after_last_ms=1500 if attempt == 0 else 2000,
            )
            await asyncio.sleep(1.5 if attempt == 0 else 2.0)
            image_bytes = await adb_service.capture_screen(serial=session.serial)
            width, height = adb_service.get_image_size(image_bytes)
            actual_fp = compute_screen_fingerprint(image_bytes)

            if not expected_fp or self.fingerprints_match(actual_fp, expected_fp):
                target_screen.status = "exploring"
                return image_bytes, width, height
            if parent_fp and not self.fingerprints_match(actual_fp, parent_fp):
                logger.warning(
                    "[monkey] 屏幕「%s」指纹与快照不完全一致，但已离开父屏幕，继续探索",
                    target_screen.title,
                )
                target_screen.status = "exploring"
                return image_bytes, width, height

            last_detail = f"期望 {expected_fp[:8]} 实际 {actual_fp[:8]}"
            logger.warning(
                "[monkey] 屏幕指纹不匹配 screen=%s attempt=%s %s",
                target_screen.title,
                attempt + 1,
                last_detail,
            )

        raise RuntimeError(
            f"真机未能进入屏幕「{target_screen.title}」，请检查回放路径（{last_detail}）"
        )

    async def navigate_to_child_screen(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        step_index: int,
        child_screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
        from_parent: MonkeyNode | None = None,
    ) -> tuple[bytes, int, int]:
        """进入子屏幕：使用子屏完整回放路径（DFS 深度探索）。"""
        if from_parent and self.is_home_screen(from_parent):
            await self.return_device_to_home(db, session, step_index=step_index)
        return await self.ensure_device_at_screen(
            db,
            session,
            step_index=step_index,
            target_screen=child_screen,
            nodes_by_uuid=nodes_by_uuid,
        )

    def collect_ancestor_actions(
        self,
        screen: MonkeyNode,
        nodes_by_uuid: dict[str, MonkeyNode],
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
    ) -> list[MonkeyScreenAction]:
        """收集当前屏幕所有祖先屏幕上的已识别元素，用于去重。"""
        collected: list[MonkeyScreenAction] = []
        current: MonkeyNode | None = screen
        seen: set[str] = set()
        while current:
            parent_screen = self._parent_screen_of(current, nodes_by_uuid)
            if not parent_screen or parent_screen.node_uuid in seen:
                break
            seen.add(parent_screen.node_uuid)
            collected.extend(actions_by_screen.get(parent_screen.node_uuid, []))
            current = parent_screen
        return collected

    def filter_launcher_candidates(
        self, candidates: list[dict], target_app_name: str
    ) -> list[dict]:
        """主屏幕只保留目标应用图标，丢弃其他桌面元素。"""
        target = (target_app_name or "").strip()
        if not target or not candidates:
            return candidates
        matched: list[dict] = []
        for item in candidates:
            title = str(item.get("element_title") or item.get("title") or "").strip()
            if self._title_matches_target(title, target):
                matched.append({**item, "element_title": target})
        if matched:
            return matched[:1]
        if len(candidates) == 1:
            return [{**candidates[0], "element_title": target}]
        return []

    @staticmethod
    def _title_matches_target(title: str, target: str) -> bool:
        left = (title or "").strip().lower()
        right = (target or "").strip().lower()
        if not left or not right:
            return False
        if left == right or left in right or right in left:
            return True
        alias_groups = [
            ("电话", "phone", "dialer", "拨号"),
            ("微信", "wechat"),
            ("相机", "camera"),
            ("设置", "settings"),
            ("短信", "messages", "message"),
            ("浏览器", "chrome", "browser"),
        ]
        for group in alias_groups:
            if any(g in right for g in group):
                if any(g in left for g in group):
                    return True
        return False

    def filter_duplicate_candidates(
        self,
        candidates: list[dict],
        *,
        screen_width: int,
        screen_height: int,
        existing_actions: list[MonkeyScreenAction],
        ancestor_actions: list[MonkeyScreenAction],
    ) -> tuple[list[dict], list[str]]:
        """与当前屏及祖先屏已有元素比对，排除重复。"""
        kept: list[dict] = []
        skipped: list[str] = []
        reference: list[tuple[str, BBox | None]] = []
        for action in existing_actions + ancestor_actions:
            bbox = BBox.model_validate_json(action.bbox_json) if action.bbox_json else None
            reference.append((action.element_title, bbox))

        for item in candidates:
            title = str(item.get("element_title") or item.get("title") or "").strip()
            if not title:
                continue
            bbox = parse_candidate_bbox(
                item.get("bbox") or item.get("box_2d") or item.get("box"),
                screen_width,
                screen_height,
            )
            if not bbox:
                continue
            duplicate = False
            for ref_title, ref_bbox in reference:
                if titles_similar(title, ref_title):
                    duplicate = True
                    break
                if ref_bbox and bbox_overlap_ratio(ref_bbox, bbox) >= 0.55:
                    duplicate = True
                    break
            if duplicate:
                skipped.append(title)
                continue
            kept.append(item)
            reference.append((title, bbox))
        return kept, skipped

    def child_screens_of(
        self,
        parent_screen: MonkeyNode,
        session: MonkeySession,
        nodes_by_uuid: dict[str, MonkeyNode],
    ) -> list[MonkeyNode]:
        children: list[tuple[int, MonkeyNode]] = []
        for node in session.nodes:
            if node.node_type != "screen":
                continue
            parent_scr = self._parent_screen_of(node, nodes_by_uuid)
            if not parent_scr or parent_scr.node_uuid != parent_screen.node_uuid:
                continue
            element = nodes_by_uuid.get(node.parent_node_uuid or "")
            action_no = 999
            if element and element.metadata_json:
                try:
                    action_no = int(json.loads(element.metadata_json).get("action_no") or 999)
                except (TypeError, ValueError):
                    pass
            children.append((action_no, node))
        children.sort(key=lambda item: (item[0], item[1].id))
        return [item[1] for item in children]

    def screen_subtree_complete(
        self,
        screen: MonkeyNode,
        session: MonkeySession,
        nodes_by_uuid: dict[str, MonkeyNode],
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
    ) -> bool:
        if not self.is_discovery_done(screen):
            return False
        actions = actions_by_screen.get(screen.node_uuid, [])
        if not actions:
            return False
        if any(a.status == "pending" for a in actions):
            return False
        for child in self.child_screens_of(screen, session, nodes_by_uuid):
            if child.status in {"discovered", "exploring"}:
                if not self.screen_subtree_complete(child, session, nodes_by_uuid, actions_by_screen):
                    return False
            elif child.status != "explored" and child.status != "skipped":
                return False
        return True

    def first_unexplored_child_screen(
        self,
        parent_screen: MonkeyNode,
        session: MonkeySession,
        nodes_by_uuid: dict[str, MonkeyNode],
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
    ) -> MonkeyNode | None:
        """按 action_no 深度优先：返回第一个尚未完成子树探索的子屏幕。"""
        for child in self.child_screens_of(parent_screen, session, nodes_by_uuid):
            if child.status == "skipped":
                continue
            if not self.screen_subtree_complete(
                child, session, nodes_by_uuid, actions_by_screen
            ):
                return child
        return None

    def exceeds_max_depth(self, screen: MonkeyNode, max_depth: int) -> bool:
        if max_depth <= 0:
            return False
        return screen.depth > max_depth

    def _parent_screen_fingerprint(
        self, screen: MonkeyNode, nodes_by_uuid: dict[str, MonkeyNode]
    ) -> str | None:
        parent = nodes_by_uuid.get(screen.parent_node_uuid or "")
        if not parent:
            return None
        if parent.node_type == "element":
            parent = nodes_by_uuid.get(parent.parent_node_uuid or "")
        if parent and parent.node_type == "screen":
            return parent.screen_fingerprint
        return None

    async def upsert_discovered_actions(
        self,
        db: AsyncSession,
        session: MonkeySession,
        *,
        screen_node: MonkeyNode,
        candidates: list[dict],
        screen_width: int,
        screen_height: int,
        replay_script: list[dict[str, Any]],
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        nodes_by_uuid: dict[str, MonkeyNode],
        ancestor_actions: list[MonkeyScreenAction] | None = None,
    ) -> list[MonkeyScreenAction]:
        if self.is_discovery_done(screen_node) and actions_by_screen.get(screen_node.node_uuid):
            return []

        existing = list(actions_by_screen.get(screen_node.node_uuid, []))
        filtered, skipped = self.filter_duplicate_candidates(
            candidates,
            screen_width=screen_width,
            screen_height=screen_height,
            existing_actions=existing,
            ancestor_actions=ancestor_actions or [],
        )
        next_no = max((a.action_no for a in existing), default=0) + 1
        created: list[MonkeyScreenAction] = []

        for item in filtered[:20]:
            title = str(item.get("element_title") or item.get("title") or "").strip()
            if not title:
                continue
            if any(a.element_title == title and a.status != "failed" for a in existing):
                continue
            bbox = parse_candidate_bbox(
                item.get("bbox") or item.get("box_2d") or item.get("box"),
                screen_width,
                screen_height,
            )
            if not bbox or bbox.w < 8 or bbox.h < 8:
                skipped.append(title)
                continue
            if bbox.x < 0 or bbox.y < 0 or bbox.x + bbox.w > screen_width + 4 or bbox.y + bbox.h > screen_height + 4:
                skipped.append(f"{title}(坐标越界)")
                continue
            center = center_from_bbox(bbox)
            logger.info(
                "[monkey] 元素「%s」bbox_raw=%s → 像素 bbox=%s center=(%s,%s) 屏 %sx%s",
                title,
                item.get("bbox") or item.get("box_2d") or item.get("box"),
                bbox.model_dump(),
                center.x,
                center.y,
                screen_width,
                screen_height,
            )
            swipe_to = None
            if item.get("swipe_to"):
                swipe_to = normalized_bbox_to_pixels(item["swipe_to"], screen_width, screen_height)
            action_type = str(item.get("suggested_action") or item.get("action_type") or "tap")
            if action_type not in {"tap", "long_press", "swipe"}:
                action_type = "tap"
            action = await monkey_repository.add_screen_action(
                db,
                session,
                screen_node_uuid=screen_node.node_uuid,
                action_no=next_no,
                element_title=title,
                action_type=action_type,
                bbox=bbox,
                center=center,
                swipe_to=swipe_to,
                data_dependency=str(item.get("data_dependency") or "无"),
                replay_script=replay_script,
            )
            element_node = await monkey_repository.add_node(
                db,
                session,
                node_type="element",
                title=title,
                parent_node_uuid=screen_node.node_uuid,
                bbox=bbox,
                center=center,
                screen_width=screen_width,
                screen_height=screen_height,
                status="discovered",
                depth=screen_node.depth + 1,
                confidence=float(item.get("confidence") or 0.8),
                description=str(item.get("reasoning") or ""),
                metadata={
                    "action_no": next_no,
                    "action_uuid": action.action_uuid,
                    "action_type": action_type,
                },
            )
            await monkey_repository.update_screen_action(
                db, action, element_node_uuid=element_node.node_uuid
            )
            nodes_by_uuid[element_node.node_uuid] = element_node
            existing.append(action)
            created.append(action)
            next_no += 1

        if created:
            screen_node.status = "exploring"
        actions_by_screen[screen_node.node_uuid] = existing
        return created, skipped

    async def finalize_screen_discovery(
        self,
        db: AsyncSession,
        session: MonkeySession,
        screen_node: MonkeyNode,
        actions: list[MonkeyScreenAction],
    ) -> None:
        """固化屏幕：锁定原始截图，生成标注图，标记发现完成。"""
        self.mark_discovery_done(screen_node)
        self.lock_screen_screenshot(screen_node)
        await self.refresh_screen_annotation(db, session, screen_node, actions)

    async def refresh_screen_annotation(
        self,
        db: AsyncSession,
        session: MonkeySession,
        screen_node: MonkeyNode,
        actions: list[MonkeyScreenAction],
    ) -> None:
        if not screen_node.screenshot_path:
            return
        image_bytes = monkey_repository.load_screenshot_bytes(
            session.session_uuid, screen_node.screenshot_path
        )
        labels: list[tuple[BBox | None, Center | None, str, str | None]] = []
        for action in sorted(actions, key=lambda item: item.action_no):
            bbox = BBox.model_validate_json(action.bbox_json) if action.bbox_json else None
            center = Center.model_validate_json(action.center_json) if action.center_json else None
            if not center and bbox:
                center = center_from_bbox(bbox)
            labels.append((bbox, center, str(action.action_no), action.status))
        annotated = annotate_screen_with_numbers(image_bytes, labels)
        meta = self.screen_metadata(screen_node)
        annotated_name = meta.get("annotated_screenshot_path")
        if not annotated_name:
            annotated_name = f"screen_{screen_node.node_uuid[:8]}_annotated.png"
            meta["annotated_screenshot_path"] = annotated_name
            screen_node.metadata_json = json.dumps(meta, ensure_ascii=False)
        monkey_repository.save_screenshot_bytes(
            session.session_uuid,
            annotated_name,
            annotated,
        )
        screen_node.annotated_screenshot_path = annotated_name
        await db.flush()

    def screen_replay_script(self, screen_node: MonkeyNode) -> list[dict[str, Any]]:
        if not screen_node.metadata_json:
            return []
        metadata = json.loads(screen_node.metadata_json)
        return list(metadata.get("replay_script") or [])

    def build_replay_for_action(
        self, screen_node: MonkeyNode, action: MonkeyScreenAction
    ) -> list[dict[str, Any]]:
        if action.replay_script_json:
            return json.loads(action.replay_script_json)
        return self.screen_replay_script(screen_node)

    def action_extra_scroll_steps(
        self, screen_node: MonkeyNode, action: MonkeyScreenAction
    ) -> list[dict[str, Any]]:
        """元素若是滚动后才发现的，其回放路径比屏幕基础路径多出滚动步骤，执行前需先回放这些滚动。"""
        base = self.screen_replay_script(screen_node)
        full = self.build_replay_for_action(screen_node, action)
        if len(full) > len(base):
            return full[len(base):]
        return []

    def actions_for_screen(self, session: MonkeySession, screen_uuid: str) -> list[MonkeyScreenAction]:
        return sorted(
            [a for a in session.screen_actions if a.screen_node_uuid == screen_uuid],
            key=lambda item: item.action_no,
        )

    def pending_actions_on_screen(
        self, session: MonkeySession, screen_uuid: str
    ) -> list[MonkeyScreenAction]:
        return [a for a in self.actions_for_screen(session, screen_uuid) if a.status == "pending"]

    def screens(self, session: MonkeySession) -> list[MonkeyNode]:
        return sorted(
            [n for n in session.nodes if n.node_type in {"root", "screen"}],
            key=lambda item: (item.depth, item.id),
        )

    def _parent_screen_of(
        self, screen: MonkeyNode, nodes_by_uuid: dict[str, MonkeyNode]
    ) -> MonkeyNode | None:
        parent = nodes_by_uuid.get(screen.parent_node_uuid or "")
        if parent and parent.node_type == "element":
            return nodes_by_uuid.get(parent.parent_node_uuid or "")
        return None

    def screen_has_pending(
        self, screen_uuid: str, actions_by_screen: dict[str, list[MonkeyScreenAction]]
    ) -> bool:
        return any(a.status == "pending" for a in actions_by_screen.get(screen_uuid, []))

    def screen_is_fully_explored(
        self,
        screen: MonkeyNode,
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
    ) -> bool:
        actions = actions_by_screen.get(screen.node_uuid, [])
        if not actions:
            return False
        return all(a.status in {"executed", "failed", "skipped", "no_effect"} for a in actions)

    def pick_next_child_screen(
        self,
        session: MonkeySession,
        nodes_by_uuid: dict[str, MonkeyNode],
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        *,
        current_focus_uuid: str,
    ) -> MonkeyNode | None:
        """父屏元素全部执行完后，按 action_no 选择下一个待探索子屏幕。"""
        explored_ids = {
            n.node_uuid
            for n in session.nodes
            if n.node_type == "screen" and n.status == "explored"
        }
        candidates: list[tuple[int, int, int, MonkeyNode]] = []

        for screen in session.nodes:
            if screen.node_type != "screen":
                continue
            if screen.node_uuid == current_focus_uuid:
                continue
            if screen.status == "explored":
                continue
            parent_screen = self._parent_screen_of(screen, nodes_by_uuid)
            if not parent_screen or parent_screen.node_uuid not in explored_ids:
                continue
            element = nodes_by_uuid.get(screen.parent_node_uuid or "")
            action_no = 999
            if element and element.metadata_json:
                try:
                    action_no = int(json.loads(element.metadata_json).get("action_no") or 999)
                except (TypeError, ValueError):
                    pass
            candidates.append((action_no, screen.depth, screen.id, screen))

        if candidates:
            candidates.sort()
            return candidates[0][3]
        return None

    def pick_next_focus_screen(
        self,
        session: MonkeySession,
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        nodes_by_uuid: dict[str, MonkeyNode] | None = None,
        *,
        current_focus_uuid: str | None = None,
    ) -> MonkeyNode | None:
        nodes_by_uuid = nodes_by_uuid or {n.node_uuid: n for n in session.nodes}
        current_focus_uuid = current_focus_uuid or self.get_focus_screen_uuid(session) or ""

        screen_nodes = sorted(
            [n for n in session.nodes if n.node_type == "screen"],
            key=lambda item: (item.depth, item.id),
        )

        for node in screen_nodes:
            if self.screen_has_pending(node.node_uuid, actions_by_screen):
                return node

        for node in screen_nodes:
            if not actions_by_screen.get(node.node_uuid):
                return node

        return self.pick_next_child_screen(
            session,
            nodes_by_uuid,
            actions_by_screen,
            current_focus_uuid=current_focus_uuid,
        )

    def mark_screen_explored_if_done(
        self,
        screen_node: MonkeyNode,
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        *,
        session: MonkeySession | None = None,
        nodes_by_uuid: dict[str, MonkeyNode] | None = None,
    ) -> None:
        if session and nodes_by_uuid:
            if not self.screen_subtree_complete(
                screen_node, session, nodes_by_uuid, actions_by_screen
            ):
                return
        else:
            actions = actions_by_screen.get(screen_node.node_uuid, [])
            if not actions:
                return
            if not all(
                a.status in {"executed", "failed", "skipped", "no_effect"} for a in actions
            ):
                return
        screen_node.status = "explored"


monkey_screen_manager = MonkeyScreenManager()
