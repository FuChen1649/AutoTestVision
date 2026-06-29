from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.launcher_locator import find_launcher_icon
from app.agent_monkey_service.navigation_tools import monkey_navigation_tools
from app.agent_monkey_service.repository import (
    compute_screen_fingerprint,
    monkey_repository,
)
from app.agent_monkey_service.run_registry import monkey_run_registry
from app.agent_monkey_service.schemas import MonkeyStreamEvent
from app.agent_monkey_service.screen_analyzer import monkey_screen_analyzer
from app.agent_monkey_service.screen_manager import monkey_screen_manager
from app.agent_monkey_service.screenshot_utils import bytes_to_data_url
from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.llm_factory import llm_factory
from app.models.monkey import MonkeyNode, MonkeyScreenAction, MonkeySession
from app.services.adb import adb_service

logger = get_agent_logger()


class MonkeyExplorer:
    MAX_DISCOVERY_SCROLLS = 3

    def _scroll_down_step(self, width: int, height: int) -> dict:
        """生成一个“向下滚动”的回放步骤（手指上滑，内容下移）。"""
        x = max(1, width // 2)
        return {
            "tool": "swipe",
            "args": {
                "x1": x,
                "y1": int(height * 0.72),
                "x2": x,
                "y2": int(height * 0.30),
                "title": "向下滚动",
            },
        }

    async def _scroll_down(self, session: MonkeySession, width: int, height: int) -> None:
        x = max(1, width // 2)
        await adb_service.swipe(
            x, int(height * 0.72), x, int(height * 0.30), serial=session.serial
        )

    async def explore(self, db: AsyncSession, session_uuid: str) -> AsyncGenerator[str, None]:
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            raise RuntimeError("会话不存在")
        if not session.serial:
            devices = await asyncio.to_thread(adb_service.list_devices)
            if not devices:
                raise RuntimeError("未连接设备")
            session.serial = devices[0].serial
            await monkey_repository.update_session(db, session, serial=session.serial)

        monkey_run_registry.register(session_uuid)
        await monkey_repository.update_session(db, session, status="running", error=None, step_count=0)
        await self._log(db, session, "开始探索：返回 Home 并建立屏幕节点", log_type="system")
        yield await self._yield_progress(db, session_uuid, "start")

        try:
            await self._log(db, session, f"设备 {session.serial}：按 Home 键返回桌面", log_type="nav")
            yield await self._yield_progress(db, session_uuid, "progress")
            await asyncio.to_thread(adb_service.go_home, session.serial)
            await asyncio.to_thread(adb_service.press_home_key, session.serial, times=2)
            await asyncio.sleep(1.0)

            await self._log(db, session, "截取 Home 屏幕", log_type="nav")
            yield await self._yield_progress(db, session_uuid, "progress")
            image_bytes = await adb_service.capture_screen(serial=session.serial)
            width, height = adb_service.get_image_size(image_bytes)
            data_url = bytes_to_data_url(image_bytes)

            await monkey_screen_manager.bootstrap_home(
                db, session, screenshot_data_url=data_url, screen_width=width, screen_height=height
            )
            await self._log(db, session, "已创建 Home 屏幕节点", log_type="screen")
            yield await self._yield_progress(db, session_uuid, "bootstrap")

            step = 0
            while True:
                if monkey_run_registry.is_cancel_requested(session_uuid):
                    session = await self._reload(db, session_uuid)
                    await monkey_repository.update_session(db, session, status="stopped")
                    await self._log(db, session, "用户停止探索", step_index=step, log_type="system")
                    yield await self._yield_progress(db, session_uuid, "progress")
                    break

                step += 1
                session = await self._reload(db, session_uuid)
                max_steps = session.max_steps
                if max_steps > 0 and step > max_steps:
                    await monkey_repository.update_session(db, session, status="completed", step_count=step - 1)
                    await self._log(
                        db,
                        session,
                        f"已达设定上限 {max_steps} 步，探索结束",
                        step_index=step - 1,
                        log_type="system",
                    )
                    yield await self._yield_progress(db, session_uuid, "step")
                    break

                nodes_by_uuid = {node.node_uuid: node for node in session.nodes}
                actions_by_screen = self._group_actions(session)

                focus_screen = self._resolve_focus_screen(session, nodes_by_uuid)
                if not focus_screen:
                    raise RuntimeError("找不到焦点屏幕节点")

                monkey_screen_manager.save_focus_screen(session, focus_screen.node_uuid)
                await self._log(
                    db,
                    session,
                    f"{self._step_label(step, max_steps)}：导航真机至「{focus_screen.title}」",
                    step_index=step,
                    log_type="nav",
                )
                yield await self._yield_progress(db, session_uuid, "progress")

                image_bytes, width, height = await monkey_screen_manager.ensure_device_at_screen(
                    db,
                    session,
                    step_index=step,
                    target_screen=focus_screen,
                    nodes_by_uuid=nodes_by_uuid,
                )
                image_bytes, width, height = self._analysis_image(
                    session.session_uuid, focus_screen, image_bytes, width, height
                )
                await self._log(
                    db,
                    session,
                    f"真机已就位「{focus_screen.title}」（{width}x{height}）",
                    step_index=step,
                    log_type="nav",
                )
                yield await self._yield_progress(db, session_uuid, "progress")
                data_url = bytes_to_data_url(image_bytes)
                screen_actions = actions_by_screen.get(focus_screen.node_uuid, [])
                pending_actions = [a for a in screen_actions if a.status == "pending"]

                async def model_progress(message: str, log_type: str) -> None:
                    await self._log(
                        db,
                        session,
                        message,
                        step_index=step,
                        log_type=log_type,
                    )

                # --- 阶段 A：首次进入屏幕，识别可探索元素（Home 仅定位目标应用图标） ---
                if not monkey_screen_manager.is_discovery_done(focus_screen):
                    ancestor_actions = monkey_screen_manager.collect_ancestor_actions(
                        focus_screen, nodes_by_uuid, actions_by_screen
                    )
                    on_home = monkey_screen_manager.is_home_screen(focus_screen)
                    phase_label = "定位目标应用" if on_home else "识别元素"
                    await self._log(
                        db,
                        session,
                        f"步骤 {step}：首次进入「{focus_screen.title}」，{phase_label}（{llm_factory.describe(session.llm_provider)}）",
                        step_index=step,
                        log_type="model",
                    )
                    yield await self._yield_progress(db, session_uuid, "progress")

                    base_script = monkey_screen_manager.screen_replay_script(focus_screen)
                    prev_fp = compute_screen_fingerprint(image_bytes)
                    total_new = 0
                    total_skipped = 0
                    max_scroll_passes = 0 if on_home else self.MAX_DISCOVERY_SCROLLS
                    for scroll_idx in range(max_scroll_passes + 1):
                        if on_home:
                            ui_hit = await find_launcher_icon(
                                session.serial, session.target_app_name
                            )
                            if ui_hit:
                                bbox, center, label = ui_hit
                                await self._log(
                                    db,
                                    session,
                                    (
                                        f"主屏 UI 层级定位「{session.target_app_name}」"
                                        f"（{label}）中心 ({center.x},{center.y})，跳过视觉模型"
                                    ),
                                    step_index=step,
                                    log_type="model",
                                )
                                analysis = {
                                    "screen_title": "主屏幕",
                                    "candidates": [
                                        {
                                            "element_title": session.target_app_name,
                                            "suggested_action": "tap",
                                            "bbox": [bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h],
                                            "data_dependency": "无",
                                            "reasoning": f"uiautomator 定位: {label}",
                                        }
                                    ],
                                }
                            else:
                                await self._log(
                                    db,
                                    session,
                                    "UI 层级未找到图标，回退视觉模型定位",
                                    step_index=step,
                                    log_type="model",
                                )
                                analysis = await monkey_screen_analyzer.discover_home_launcher(
                                    provider=session.llm_provider,
                                    target_app_name=session.target_app_name,
                                    step_index=step,
                                    max_steps=max_steps,
                                    screenshot_data_url=data_url,
                                    screen_width=width,
                                    screen_height=height,
                                    on_progress=model_progress,
                                )
                        else:
                            explore_state = self._build_explore_state(
                                session,
                                focus_screen,
                                actions_by_screen,
                                phase="discover",
                                ancestor_actions=ancestor_actions,
                            )
                            analysis = await monkey_screen_analyzer.discover_screen(
                                provider=session.llm_provider,
                                target_app_name=session.target_app_name,
                                step_index=step,
                                max_steps=max_steps,
                                explore_state=explore_state,
                                screenshot_data_url=data_url,
                                screen_width=width,
                                screen_height=height,
                                on_progress=model_progress,
                            )
                        yield await self._yield_progress(db, session_uuid, "progress")

                        if (
                            scroll_idx == 0
                            and analysis.get("screen_title")
                            and not monkey_screen_manager.is_screenshot_locked(focus_screen)
                            and not on_home
                        ):
                            focus_screen.title = str(analysis["screen_title"])[:120]
                        if scroll_idx == 0 and not focus_screen.screenshot_path:
                            await self._freeze_screen_snapshot(
                                session, focus_screen, image_bytes, width, height
                            )

                        candidates = analysis.get("candidates") or []
                        if on_home:
                            candidates = monkey_screen_manager.filter_launcher_candidates(
                                candidates, session.target_app_name
                            )

                        scroll_script = base_script + [
                            self._scroll_down_step(width, height)
                        ] * scroll_idx
                        new_actions, skipped = await monkey_screen_manager.upsert_discovered_actions(
                            db,
                            session,
                            screen_node=focus_screen,
                            candidates=candidates,
                            screen_width=width,
                            screen_height=height,
                            replay_script=scroll_script,
                            actions_by_screen=actions_by_screen,
                            nodes_by_uuid=nodes_by_uuid,
                            ancestor_actions=ancestor_actions,
                        )
                        total_new += len(new_actions)
                        total_skipped += len(skipped)

                        scrollable = bool(analysis.get("scrollable")) and not bool(
                            analysis.get("reached_bottom")
                        )
                        if not scrollable or scroll_idx >= self.MAX_DISCOVERY_SCROLLS:
                            break
                        await self._log(
                            db, session, "页面可滚动，向下滚动继续发现元素", step_index=step, log_type="nav"
                        )
                        await self._scroll_down(session, width, height)
                        await asyncio.sleep(0.8)
                        image_bytes = await adb_service.capture_screen(serial=session.serial)
                        width, height = adb_service.get_image_size(image_bytes)
                        data_url = bytes_to_data_url(image_bytes)
                        new_fp = compute_screen_fingerprint(image_bytes)
                        if monkey_screen_manager.fingerprints_match(new_fp, prev_fp):
                            break
                        prev_fp = new_fp

                    all_screen_actions = actions_by_screen.get(focus_screen.node_uuid, [])
                    await monkey_screen_manager.finalize_screen_discovery(
                        db, session, focus_screen, all_screen_actions
                    )
                    skip_msg = f"，排除重复 {total_skipped} 个" if total_skipped else ""
                    await self._log(
                        db,
                        session,
                        f"「{focus_screen.title}」识别到 {len(all_screen_actions)} 个元素（新增 {total_new}{skip_msg}），截图已固化",
                        step_index=step,
                        log_type="screen",
                    )
                    await monkey_repository.update_session(
                        db, session, step_count=step, current_node_uuid=focus_screen.node_uuid
                    )
                    yield await self._yield_progress(db, session_uuid, "step")
                    continue

                # --- 阶段 B：深度优先 — 执行当前屏第一个 pending，再进入其子屏 ---
                if pending_actions:
                    action = pending_actions[0]
                    await self._log(
                        db,
                        session,
                        f"步骤 {step}：执行 #{action.action_no} {action.element_title}（{action.action_type}）",
                        step_index=step,
                        log_type="action",
                    )
                    yield await self._yield_progress(db, session_uuid, "progress")
                    before_data_url = data_url
                    try:
                        extra_steps = monkey_screen_manager.action_extra_scroll_steps(
                            focus_screen, action
                        )
                        if extra_steps:
                            await monkey_navigation_tools.replay_script(
                                db,
                                session,
                                step_index=step,
                                script=extra_steps,
                                nodes_by_uuid=nodes_by_uuid,
                            )
                            await asyncio.sleep(0.6)
                        nav_result = await monkey_navigation_tools.execute_screen_action(
                            db,
                            session,
                            step_index=step,
                            action=action,
                            nodes_by_uuid=nodes_by_uuid,
                        )
                        if action.element_node_uuid and action.element_node_uuid in nodes_by_uuid:
                            nodes_by_uuid[action.element_node_uuid].status = "explored"
                    except Exception as exc:
                        await monkey_repository.update_screen_action(
                            db, action, status="failed", step_index=step
                        )
                        await self._log(
                            db,
                            session,
                            f"操作 #{action.action_no} 失败: {exc}",
                            step_index=step,
                            log_type="action",
                        )
                        await monkey_repository.update_session(db, session, step_count=step)
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue

                    await self._log(
                        db,
                        session,
                        nav_result.get("message", "已执行操作"),
                        step_index=step,
                        log_type="action",
                        detail=nav_result,
                    )
                    if action.center_json:
                        from app.agent_monkey_service.schemas import Center

                        tap = Center.model_validate_json(action.center_json)
                        await self._log(
                            db,
                            session,
                            f"真机点击坐标 ({tap.x}, {tap.y})",
                            step_index=step,
                            log_type="action",
                        )
                    yield await self._yield_progress(db, session_uuid, "progress")

                    await self._log(db, session, "截取操作后屏幕，判断页面归属", step_index=step, log_type="screen")
                    await asyncio.sleep(1.0)
                    after_bytes = await adb_service.capture_screen(serial=session.serial)
                    after_width, after_height = adb_service.get_image_size(after_bytes)
                    after_data_url = bytes_to_data_url(after_bytes)
                    after_fp = compute_screen_fingerprint(after_bytes)

                    session = await self._reload(db, session_uuid)
                    nodes_by_uuid = {node.node_uuid: node for node in session.nodes}
                    focus_screen = nodes_by_uuid[focus_screen.node_uuid]
                    action = next(
                        (a for a in session.screen_actions if a.action_uuid == action.action_uuid),
                        action,
                    )

                    # --- 算法初判（感知指纹）+ AI 语义确认，共同决定子节点归属 ---
                    before_fp = focus_screen.screen_fingerprint
                    known_state = monkey_screen_manager.find_state_by_fingerprint(
                        nodes_by_uuid, after_fp, exclude_uuid=focus_screen.node_uuid
                    )
                    if monkey_screen_manager.fingerprints_match(after_fp, before_fp):
                        algo_guess, candidate_title = "same_state", focus_screen.title
                    elif known_state is not None:
                        algo_guess, candidate_title = "revisit", known_state.title
                    else:
                        algo_guess, candidate_title = "new_state", None

                    relation, ai_title, judged = algo_guess, None, None
                    try:
                        judged = await monkey_screen_analyzer.judge_transition(
                            provider=session.llm_provider,
                            target_app_name=session.target_app_name,
                            step_index=step,
                            action_title=action.element_title,
                            action_type=action.action_type,
                            before_data_url=before_data_url,
                            after_data_url=after_data_url,
                            algo_guess=algo_guess,
                            candidate_title=candidate_title,
                            known_titles=monkey_screen_manager.known_screen_titles(nodes_by_uuid),
                            on_progress=model_progress,
                        )
                        relation = judged.get("relation", algo_guess)
                        ai_title = judged.get("screen_title")
                    except Exception as exc:
                        await self._log(
                            db,
                            session,
                            f"交互归属模型判断失败，回退算法初判（{algo_guess}）：{exc}",
                            step_index=step,
                            log_type="model",
                        )

                    # 指纹已变化或算法初判为新页面时，不信任 same_state/no_effect
                    if relation in {"same_state", "no_effect"}:
                        if not monkey_screen_manager.fingerprints_match(after_fp, before_fp):
                            relation = "new_state"
                        elif algo_guess == "new_state":
                            relation = "new_state"

                    # 无新页面：仅记录，不建子节点
                    if relation in {"same_state", "no_effect"}:
                        on_home = monkey_screen_manager.is_home_screen(focus_screen)
                        launcher_miss = on_home and monkey_screen_manager._title_matches_target(
                            action.element_title, session.target_app_name
                        )
                        fail_status = "failed" if launcher_miss else (
                            "no_effect" if relation == "no_effect" else "executed"
                        )
                        await monkey_repository.update_screen_action(
                            db,
                            action,
                            status=fail_status,
                            step_index=step,
                        )
                        if launcher_miss:
                            monkey_screen_manager.reset_discovery(focus_screen)
                        await self._log(
                            db,
                            session,
                            (
                                f"#{action.action_no} {action.element_title}："
                                + (
                                    "主屏点击未启动应用，坐标可能不准，将重新定位"
                                    if launcher_miss
                                    else (
                                        "无明显效果"
                                        if relation == "no_effect"
                                        else "仍停留在当前页面"
                                    )
                                )
                                + ("，不新建子页面" if not launcher_miss else "")
                            ),
                            step_index=step,
                            log_type="action",
                        )
                        await self._refresh_focus_annotation(
                            db, session, focus_screen, actions_by_screen, action
                        )
                        await monkey_repository.update_session(
                            db, session, step_count=step, current_node_uuid=focus_screen.node_uuid
                        )
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue

                    # 回到已知页面：连一条引用边，不重复探索
                    if relation == "revisit":
                        target = known_state
                        if target is None and judged is not None:
                            same_title = judged.get("same_as_known_title")
                            if same_title:
                                target = next(
                                    (
                                        n
                                        for n in nodes_by_uuid.values()
                                        if n.node_type == "screen" and n.title == same_title
                                    ),
                                    None,
                                )
                        await monkey_repository.update_screen_action(
                            db,
                            action,
                            status="executed",
                            step_index=step,
                            result_screen_uuid=target.node_uuid if target else None,
                        )
                        await self._log(
                            db,
                            session,
                            f"#{action.action_no} {action.element_title}：回到已知页面"
                            + (f"「{target.title}」" if target else "")
                            + "，连引用边不重复探索",
                            step_index=step,
                            log_type="nav",
                        )
                        await self._refresh_focus_annotation(
                            db, session, focus_screen, actions_by_screen, action
                        )
                        await monkey_repository.update_session(
                            db, session, step_count=step, current_node_uuid=focus_screen.node_uuid
                        )
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue

                    # new_state：新建子页面节点
                    await monkey_repository.update_screen_action(
                        db, action, status="executed", step_index=step
                    )
                    element_parent = (
                        nodes_by_uuid.get(action.element_node_uuid or "")
                        if action.element_node_uuid
                        else None
                    )
                    parent_uuid = element_parent.node_uuid if element_parent else focus_screen.node_uuid
                    action_replay = monkey_screen_manager.build_replay_for_action(
                        focus_screen, action
                    ) + [monkey_navigation_tools.action_to_replay_step(action)]
                    child_title = (
                        str(ai_title)[:120]
                        if ai_title
                        else f"#{action.action_no} {action.element_title}"
                    )
                    result_screen = await monkey_screen_manager.ensure_screen_node(
                        db,
                        session,
                        fingerprint=after_fp,
                        screenshot_data_url=after_data_url,
                        screen_width=after_width,
                        screen_height=after_height,
                        title=child_title,
                        parent_node_uuid=parent_uuid,
                        depth=(element_parent.depth if element_parent else focus_screen.depth) + 1,
                        replay_script=action_replay,
                        nodes_by_uuid=nodes_by_uuid,
                        triggered_by_action_uuid=action.action_uuid,
                    )
                    await monkey_repository.update_screen_action(
                        db, action, result_screen_uuid=result_screen.node_uuid
                    )

                    actions_by_screen = self._group_actions(session)
                    await self._refresh_focus_annotation(
                        db, session, focus_screen, actions_by_screen, action
                    )

                    if monkey_screen_manager.exceeds_max_depth(result_screen, session.max_depth):
                        result_screen.status = "skipped"
                        await self._log(
                            db,
                            session,
                            f"子屏「{result_screen.title}」超过最大深度 {session.max_depth}，跳过",
                            step_index=step,
                            log_type="nav",
                        )
                        await monkey_screen_manager.return_device_to_focus_screen(
                            db,
                            session,
                            step_index=step,
                            focus_screen=focus_screen,
                            nodes_by_uuid=nodes_by_uuid,
                        )
                        await monkey_repository.update_session(
                            db, session, step_count=step, current_node_uuid=focus_screen.node_uuid
                        )
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue

                    monkey_screen_manager.push_explore_stack(session, result_screen.node_uuid)
                    await self._log(
                        db,
                        session,
                        f"深度优先进入子屏「{result_screen.title}」，完成后再回「{focus_screen.title}」继续",
                        step_index=step,
                        log_type="nav",
                    )
                    await monkey_repository.update_session(
                        db, session, step_count=step, current_node_uuid=result_screen.node_uuid
                    )
                    yield await self._yield_progress(db, session_uuid, "step")
                    continue

                # --- 阶段 C：当前屏无 pending，检查是否还有未完成的子屏（DFS） ---
                child_focus = monkey_screen_manager.first_unexplored_child_screen(
                    focus_screen, session, nodes_by_uuid, actions_by_screen
                )
                if child_focus:
                    await self._log(
                        db,
                        session,
                        f"进入子屏「{child_focus.title}」继续深度探索",
                        step_index=step,
                        log_type="nav",
                    )
                    yield await self._yield_progress(db, session_uuid, "progress")
                    try:
                        await monkey_screen_manager.navigate_to_child_screen(
                            db,
                            session,
                            step_index=step,
                            child_screen=child_focus,
                            nodes_by_uuid=nodes_by_uuid,
                            from_parent=focus_screen,
                        )
                        monkey_screen_manager.push_explore_stack(session, child_focus.node_uuid)
                        await monkey_repository.update_session(
                            db, session, step_count=step, current_node_uuid=child_focus.node_uuid
                        )
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue
                    except Exception as exc:
                        await self._log(
                            db,
                            session,
                            f"进入子屏幕失败: {exc}",
                            step_index=step,
                            log_type="nav",
                        )
                        child_focus.status = "failed"
                        await monkey_repository.update_session(
                            db, session, step_count=step
                        )
                        yield await self._yield_progress(db, session_uuid, "step")
                        continue

                # --- 阶段 D：当前屏及子树已完成，回退到父屏 ---
                monkey_screen_manager.mark_screen_explored_if_done(
                    focus_screen,
                    actions_by_screen,
                    session=session,
                    nodes_by_uuid=nodes_by_uuid,
                )
                stack = monkey_screen_manager.get_explore_stack(session)
                if len(stack) <= 1:
                    await monkey_repository.update_session(db, session, status="completed", step_count=step)
                    await self._log(db, session, "所有屏幕已探索完毕", step_index=step, log_type="system")
                    yield await self._yield_progress(db, session_uuid, "step")
                    break

                parent_uuid = monkey_screen_manager.pop_explore_stack(session)
                if not parent_uuid:
                    await monkey_repository.update_session(db, session, status="completed", step_count=step)
                    await self._log(db, session, "所有屏幕已探索完毕", step_index=step, log_type="system")
                    yield await self._yield_progress(db, session_uuid, "step")
                    break

                parent_screen = nodes_by_uuid.get(parent_uuid)
                if not parent_screen:
                    raise RuntimeError("探索栈中的父屏幕不存在")

                await self._log(
                    db,
                    session,
                    f"「{focus_screen.title}」子树已完成，回退至「{parent_screen.title}」",
                    step_index=step,
                    log_type="nav",
                )
                yield await self._yield_progress(db, session_uuid, "progress")
                await monkey_screen_manager.return_to_parent_via_back(
                    db,
                    session,
                    step_index=step,
                    parent_screen=parent_screen,
                    nodes_by_uuid=nodes_by_uuid,
                )
                await monkey_repository.update_session(
                    db, session, step_count=step, current_node_uuid=parent_screen.node_uuid
                )
                yield await self._yield_progress(db, session_uuid, "step")

        except asyncio.CancelledError:
            session = await self._reload(db, session_uuid)
            if session:
                await monkey_repository.update_session(db, session, status="stopped")
                await self._log(db, session, "探索已取消", log_type="system")
        except Exception as exc:
            logger.exception("[monkey_explorer] session=%s failed", session_uuid)
            session = await self._reload(db, session_uuid)
            if session:
                await monkey_repository.update_session(db, session, status="failed", error=str(exc))
                await self._log(db, session, f"探索失败: {exc}", log_type="system")
            yield self._sse(
                MonkeyStreamEvent(
                    type="error",
                    message=str(exc),
                    session=monkey_repository.session_to_response(session) if session else None,
                )
            )
        finally:
            monkey_run_registry.clear(session_uuid)

        session = await self._reload(db, session_uuid)
        yield self._sse(
            MonkeyStreamEvent(
                type="done",
                session=monkey_repository.session_to_response(session) if session else None,
                message=f"探索结束：{session.status if session else 'unknown'}",
            )
        )

    def _analysis_image(
        self,
        session_uuid: str,
        screen: MonkeyNode,
        live_bytes: bytes,
        live_width: int,
        live_height: int,
    ) -> tuple[bytes, int, int]:
        """已固化屏幕始终用原始截图做分析/标注，避免动态界面导致节点消失。"""
        if monkey_screen_manager.is_screenshot_locked(screen) and screen.screenshot_path:
            frozen = monkey_repository.load_screenshot_bytes(session_uuid, screen.screenshot_path)
            return frozen, screen.screen_width or live_width, screen.screen_height or live_height
        return live_bytes, live_width, live_height

    async def _freeze_screen_snapshot(
        self,
        session: MonkeySession,
        screen: MonkeyNode,
        image_bytes: bytes,
        width: int,
        height: int,
    ) -> None:
        if screen.screenshot_path:
            return
        shot_name = monkey_repository.save_screenshot_bytes(
            session.session_uuid,
            f"screen_{screen.node_uuid[:8]}_base.png",
            image_bytes,
        )
        screen.screenshot_path = shot_name
        screen.annotated_screenshot_path = shot_name
        screen.screen_width = width
        screen.screen_height = height
        screen.screen_fingerprint = compute_screen_fingerprint(image_bytes)

    async def _log(
        self,
        db: AsyncSession,
        session: MonkeySession,
        message: str,
        *,
        log_type: str = "system",
        step_index: int | None = None,
        detail: dict | None = None,
    ) -> None:
        await monkey_repository.add_log(
            db,
            session,
            message,
            log_type=log_type,
            step_index=step_index,
            detail=detail,
        )
        await db.commit()
        logger.info("[monkey] session=%s %s", session.session_uuid[:8], message)

    async def _reload(self, db: AsyncSession, session_uuid: str) -> MonkeySession:
        db.expire_all()
        session = await monkey_repository.get_session(db, session_uuid)
        if not session:
            raise RuntimeError("会话不存在")
        return session

    async def _yield_progress(
        self, db: AsyncSession, session_uuid: str, event_type: str
    ) -> str:
        session = await self._reload(db, session_uuid)
        state = monkey_repository.explore_state_to_response(session)
        return self._sse(
            MonkeyStreamEvent(
                type=event_type,
                session=state.session,
                screens=state.screens,
                actions=state.actions,
                nodes=state.tree_nodes,
                logs=state.logs[-30:],
            )
        )

    def _step_label(self, step: int, max_steps: int) -> str:
        if max_steps > 0:
            return f"步骤 {step}/{max_steps}"
        return f"步骤 {step}"

    def _resolve_focus_screen(
        self, session: MonkeySession, nodes_by_uuid: dict[str, MonkeyNode]
    ) -> MonkeyNode | None:
        focus_uuid = monkey_screen_manager.get_focus_screen_uuid(session)
        focus_screen = nodes_by_uuid.get(focus_uuid or "")
        if focus_screen and focus_screen.node_type == "screen":
            return focus_screen

        screens = sorted(
            [n for n in nodes_by_uuid.values() if n.node_type == "screen"],
            key=lambda item: (item.depth, item.id),
        )
        return screens[0] if screens else None

    def _group_actions(self, session: MonkeySession) -> dict[str, list[MonkeyScreenAction]]:
        grouped: dict[str, list[MonkeyScreenAction]] = {}
        for action in session.screen_actions:
            grouped.setdefault(action.screen_node_uuid, []).append(action)
        for items in grouped.values():
            items.sort(key=lambda item: item.action_no)
        return grouped

    def _build_explore_state(
        self,
        session: MonkeySession,
        focus_screen: MonkeyNode,
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        *,
        phase: str,
        ancestor_actions: list[MonkeyScreenAction] | None = None,
    ) -> dict:
        element_children = [
            {
                "node_uuid": n.node_uuid,
                "title": n.title,
                "status": n.status,
                "action_no": (
                    json.loads(n.metadata_json).get("action_no") if n.metadata_json else None
                ),
            }
            for n in session.nodes
            if n.parent_node_uuid == focus_screen.node_uuid and n.node_type == "element"
        ]
        actions = actions_by_screen.get(focus_screen.node_uuid, [])
        parent_screen = monkey_screen_manager._parent_screen_of(focus_screen, {n.node_uuid: n for n in session.nodes})
        parent_actions = (
            actions_by_screen.get(parent_screen.node_uuid, []) if parent_screen else []
        )
        return {
            "phase": phase,
            "target_app_name": session.target_app_name,
            "is_home_screen": monkey_screen_manager.is_home_screen(focus_screen),
            "focus_screen_uuid": focus_screen.node_uuid,
            "focus_screen_title": focus_screen.title,
            "max_depth": session.max_depth,
            "element_children": element_children,
            "known_elements": [
                a.element_title for a in actions_by_screen.get(focus_screen.node_uuid, [])
            ],
            "parent_screen_elements": [
                {"action_no": a.action_no, "element_title": a.element_title}
                for a in parent_actions
            ],
            "ancestor_elements": [
                {"element_title": a.element_title, "screen_action": a.action_no}
                for a in (ancestor_actions or [])
            ],
            "actions": [
                {
                    "action_no": a.action_no,
                    "element_title": a.element_title,
                    "action_type": a.action_type,
                    "status": a.status,
                    "data_dependency": a.data_dependency,
                }
                for a in actions
            ],
            "pending_count": len([a for a in actions if a.status == "pending"]),
            "explored_count": len([a for a in actions if a.status == "executed"]),
            "strategy": "深度优先：执行 #1 并探索完其子树，再执行 #2…；子屏排除与父屏重复元素；截图固化不变",
        }

    async def _refresh_focus_annotation(
        self,
        db: AsyncSession,
        session: MonkeySession,
        focus_screen: MonkeyNode,
        actions_by_screen: dict[str, list[MonkeyScreenAction]],
        updated_action: MonkeyScreenAction | None = None,
    ) -> None:
        actions = list(actions_by_screen.get(focus_screen.node_uuid, []))
        if updated_action:
            actions = [
                updated_action if a.action_uuid == updated_action.action_uuid else a
                for a in actions
            ]
        await monkey_screen_manager.refresh_screen_annotation(db, session, focus_screen, actions)

    def _sse(self, event: MonkeyStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"


monkey_explorer = MonkeyExplorer()
