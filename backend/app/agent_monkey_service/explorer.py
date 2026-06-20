from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_monkey_service.navigation_tools import monkey_navigation_tools
from app.agent_monkey_service.repository import (
    compute_screen_fingerprint,
    monkey_repository,
)
from app.agent_monkey_service.run_registry import monkey_run_registry
from app.agent_monkey_service.schemas import MonkeyLogItem, MonkeyStreamEvent
from app.agent_monkey_service.screen_analyzer import monkey_screen_analyzer
from app.agent_monkey_service.screenshot_utils import bytes_to_data_url
from app.agent_monkey_service.tree_manager import monkey_tree_manager
from app.agent_test_service.agent_logger import get_agent_logger
from app.models.monkey import MonkeyNode, MonkeySession
from app.services.adb import adb_service

logger = get_agent_logger()


class MonkeyExplorer:
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
        await monkey_repository.add_log(db, session, "开始探索：强制返回 Home")
        await db.commit()

        yield self._sse(MonkeyStreamEvent(type="start", session=monkey_repository.session_to_response(session)))

        try:
            await asyncio.to_thread(adb_service.go_home, session.serial)
            await asyncio.to_thread(adb_service.press_home_key, session.serial, times=2)
            await asyncio.sleep(1.0)

            image_bytes = await adb_service.capture_screen(serial=session.serial)
            width, height = adb_service.get_image_size(image_bytes)
            data_url = bytes_to_data_url(image_bytes)

            root, home = await monkey_tree_manager.bootstrap_home(
                db, session, screenshot_data_url=data_url, screen_width=width, screen_height=height
            )
            await monkey_repository.add_log(db, session, "已创建根节点与 Home 屏幕节点")
            await db.commit()
            session = await monkey_repository.get_session(db, session_uuid)
            assert session
            nodes_by_uuid = {node.node_uuid: node for node in session.nodes}

            yield self._sse(
                MonkeyStreamEvent(
                    type="tree_update",
                    session=monkey_repository.session_to_response(session),
                    nodes=[
                        monkey_repository.node_to_response(session_uuid, root),
                        monkey_repository.node_to_response(session_uuid, home),
                    ],
                )
            )

            step = 0
            while step < session.max_steps:
                if monkey_run_registry.is_cancel_requested(session_uuid):
                    await monkey_repository.update_session(db, session, status="stopped")
                    await monkey_repository.add_log(db, session, "用户停止探索", step_index=step)
                    await db.commit()
                    break

                step += 1
                session = await monkey_repository.get_session(db, session_uuid)
                assert session
                nodes_by_uuid = {node.node_uuid: node for node in session.nodes}
                current = nodes_by_uuid.get(session.current_node_uuid or "")
                if not current:
                    current = next((n for n in nodes_by_uuid.values() if n.node_type == "screen"), None)
                if not current:
                    raise RuntimeError("找不到当前 screen 节点")

                image_bytes = await adb_service.capture_screen(serial=session.serial)
                width, height = adb_service.get_image_size(image_bytes)
                data_url = bytes_to_data_url(image_bytes)
                fingerprint = compute_screen_fingerprint(image_bytes)

                tree_json = monkey_tree_manager.tree_for_prompt(session, nodes_by_uuid)
                action_history = [
                    {
                        "step_index": record.step_index,
                        "tool_name": record.tool_name,
                        "node_uuid": record.node_uuid,
                        "x": record.x,
                        "y": record.y,
                        "title": record.title,
                        "result": record.result,
                    }
                    for record in sorted(session.actions, key=lambda item: item.step_index)
                ]

                await monkey_repository.add_log(
                    db,
                    session,
                    f"步骤 {step}：调用模型分析屏幕",
                    step_index=step,
                    log_type="model",
                )
                await db.commit()

                analysis = await monkey_screen_analyzer.analyze_step(
                    provider=session.llm_provider,
                    target_app_name=session.target_app_name,
                    step_index=step,
                    max_steps=session.max_steps,
                    tree_json=tree_json,
                    action_history=action_history,
                    screenshot_data_url=data_url,
                    screen_width=width,
                    screen_height=height,
                )

                discovered = analysis.get("discovered_nodes") or []
                new_nodes = await monkey_tree_manager.merge_discovered_nodes(
                    db,
                    session,
                    parent_node=current,
                    discovered=discovered,
                    screenshot_data_url=data_url,
                    screen_width=width,
                    screen_height=height,
                    screen_fingerprint=fingerprint,
                    nodes_by_uuid=nodes_by_uuid,
                )
                await monkey_repository.add_log(
                    db,
                    session,
                    f"发现 {len(new_nodes)} 个新节点",
                    step_index=step,
                    log_type="tree",
                    detail={"count": len(new_nodes)},
                )

                tool_call = analysis.get("tool_call") or {}
                tool_name = str(tool_call.get("name") or "stop")
                args = dict(tool_call.get("args") or {})
                args.setdefault("screen_width", width)
                args.setdefault("screen_height", height)

                session = await monkey_repository.get_session(db, session_uuid)
                assert session
                nodes_by_uuid = {node.node_uuid: node for node in session.nodes}

                if step == 1 and session.target_app_name:
                    target_nodes = [
                        n
                        for n in nodes_by_uuid.values()
                        if n.node_type == "app"
                        and session.target_app_name.lower() in n.title.lower()
                        and n.status == "discovered"
                    ]
                    if target_nodes and tool_name not in {"tap_node", "navigate_to_node", "tap_coordinates"}:
                        tool_name = "tap_node"
                        args = {"node_uuid": target_nodes[0].node_uuid}

                nav_result = await monkey_navigation_tools.execute(
                    db,
                    session,
                    step_index=step,
                    tool_name=tool_name,
                    args=args,
                    nodes_by_uuid=nodes_by_uuid,
                )
                await monkey_repository.add_log(
                    db,
                    session,
                    nav_result.get("message", tool_name),
                    step_index=step,
                    log_type="action",
                    detail=nav_result,
                )
                await monkey_repository.update_session(db, session, step_count=step)
                await db.commit()

                session = await monkey_repository.get_session(db, session_uuid)
                assert session
                yield self._sse(
                    MonkeyStreamEvent(
                        type="step",
                        session=monkey_repository.session_to_response(session),
                        nodes=[monkey_repository.node_to_response(session_uuid, n) for n in new_nodes],
                        logs=[
                            MonkeyLogItem(
                                id=-step,
                                step_index=step,
                                log_type="action",
                                message=str(nav_result.get("message", tool_name)),
                                detail=nav_result,
                                created_at=session.updated_at,
                            )
                        ],
                    )
                )

                if tool_name == "stop" or nav_result.get("result") == "stop":
                    await monkey_repository.update_session(db, session, status="completed")
                    await db.commit()
                    break
            else:
                await monkey_repository.update_session(db, session, status="completed")
                await db.commit()

        except asyncio.CancelledError:
            session = await monkey_repository.get_session(db, session_uuid)
            if session:
                await monkey_repository.update_session(db, session, status="stopped")
                await monkey_repository.add_log(db, session, "探索已取消")
                await db.commit()
        except Exception as exc:
            logger.exception("[monkey_explorer] session=%s failed", session_uuid)
            session = await monkey_repository.get_session(db, session_uuid)
            if session:
                await monkey_repository.update_session(db, session, status="failed", error=str(exc))
                await monkey_repository.add_log(db, session, f"探索失败: {exc}")
                await db.commit()
            yield self._sse(
                MonkeyStreamEvent(type="error", message=str(exc), session=monkey_repository.session_to_response(session) if session else None)
            )
        finally:
            monkey_run_registry.clear(session_uuid)

        session = await monkey_repository.get_session(db, session_uuid)
        yield self._sse(
            MonkeyStreamEvent(
                type="done",
                session=monkey_repository.session_to_response(session) if session else None,
                message=f"探索结束：{session.status if session else 'unknown'}",
            )
        )

    def _sse(self, event: MonkeyStreamEvent) -> str:
        return f"data: {event.model_dump_json()}\n\n"


monkey_explorer = MonkeyExplorer()
