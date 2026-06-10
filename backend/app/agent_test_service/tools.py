"""Agent 可调用的确定性工具（ADB / 系统能力），不经过 LLM 视觉分析。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.log_stream import emit as emit_live
from app.agent_test_service.schemas import ActionIntent, StepExecutionRecord, VerificationResult
from app.services.adb import adb_service

logger = get_agent_logger()

PERMISSION_PRESET_TYPE = "permission_preset"
TOOL_APPLY_APP_PERMISSIONS = "apply_app_permissions"
TOOL_RECOVER_SCENE = "recover_scene"

# step_type -> 默认工具名
STEP_TYPE_TOOLS: dict[str, str] = {
    PERMISSION_PRESET_TYPE: TOOL_APPLY_APP_PERMISSIONS,
}


@dataclass
class ToolExecutionResult:
    success: bool
    message: str
    detail: dict[str, Any]
    intent: ActionIntent | None = None
    verification: VerificationResult | None = None


def is_tool_step(step_type: str) -> bool:
    return step_type in STEP_TYPE_TOOLS


def resolve_tool_name(step_type: str, metadata: dict[str, Any] | None) -> str | None:
    if metadata and metadata.get("tool"):
        return str(metadata["tool"])
    return STEP_TYPE_TOOLS.get(step_type)


def parse_step_metadata(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


class AgentTools:
    """封装模型/ Harness 可调用的工具函数。"""

    async def run_for_step(
        self, step: StepExecutionRecord, *, serial: str | None
    ) -> ToolExecutionResult:
        metadata = step.metadata or {}
        tool_name = resolve_tool_name(step.step_type, metadata)
        if not tool_name:
            message = f"未注册的工具步骤类型: {step.step_type}"
            logger.warning("[tools] %s", message)
            return ToolExecutionResult(success=False, message=message, detail={})

        logger.info("[tools] 执行 tool=%s step_order=%d", tool_name, step.step_order)
        emit_live("intent", f"工具步骤，跳过 LLM，调用 {tool_name}", detail={"tool": tool_name})

        if tool_name == TOOL_APPLY_APP_PERMISSIONS:
            return await self.apply_app_permissions(metadata, serial=serial)

        message = f"工具未实现: {tool_name}"
        return ToolExecutionResult(success=False, message=message, detail={"tool": tool_name})

    async def apply_app_permissions(
        self, metadata: dict[str, Any], *, serial: str | None
    ) -> ToolExecutionResult:
        package = metadata.get("package")
        permissions = metadata.get("permissions") or []

        if not package:
            message = "权限步骤缺少应用包名，请在 Case 构建页配置应用与权限后重新保存"
            emit_live("executor", message)
            return ToolExecutionResult(
                success=False,
                message=message,
                detail={"error": "missing_package"},
                intent=ActionIntent(action="skip", confidence=0.0, reasoning=message),
                verification=VerificationResult(success=False, confidence=0.0, reasoning=message),
            )

        if not isinstance(permissions, list) or not permissions:
            message = "权限步骤缺少权限列表，请在 Case 构建页勾选权限后重新保存"
            emit_live("executor", message)
            return ToolExecutionResult(
                success=False,
                message=message,
                detail={"error": "missing_permissions", "package": package},
                intent=ActionIntent(action="skip", confidence=0.0, reasoning=message),
                verification=VerificationResult(success=False, confidence=0.0, reasoning=message),
            )

        permission_names = [str(item) for item in permissions]
        emit_live(
            "executor",
            f"ADB 刷新应用权限 package={package} count={len(permission_names)}",
            detail={"package": package, "permissions": permission_names},
        )
        logger.info(
            "[tools:apply_app_permissions] package=%s permissions=%d serial=%s",
            package,
            len(permission_names),
            serial,
        )

        try:
            result = adb_service.apply_app_permissions(package, permission_names, serial=serial)
        except RuntimeError as exc:
            message = str(exc)
            emit_live("executor", f"权限刷新失败: {message}")
            return ToolExecutionResult(
                success=False,
                message=message,
                detail={"package": package},
                intent=ActionIntent(action="skip", confidence=0.0, reasoning=message),
                verification=VerificationResult(success=False, confidence=0.0, reasoning=message),
            )

        detail = {
            "package": result.package,
            "granted": result.granted,
            "revoked": result.revoked,
            "skipped": result.skipped,
            "errors": result.errors,
        }
        success = len(result.errors) == 0
        parts = [
            f"已授予 {len(result.granted)} 项" if result.granted else "",
            f"已撤销 {len(result.revoked)} 项" if result.revoked else "",
            f"{len(result.skipped)} 项不可变更" if result.skipped else "",
            f"{len(result.errors)} 项失败" if result.errors else "",
        ]
        message = "，".join(part for part in parts if part) or "权限已刷新"
        if not success:
            message = f"{message}；错误: {'; '.join(result.errors[:3])}"

        emit_live(
            "verifier",
            "工具执行" + ("成功" if success else "失败") + f": {message}",
            detail=detail,
        )

        intent = ActionIntent(action="skip", confidence=1.0 if success else 0.0, reasoning=message)
        verification = VerificationResult(
            success=success,
            confidence=1.0 if success else 0.0,
            reasoning=message,
        )
        return ToolExecutionResult(
            success=success,
            message=message,
            detail=detail,
            intent=intent,
            verification=verification,
        )

    async def recover_scene(self, *, serial: str | None) -> dict[str, Any]:
        """执行前场景恢复：清后台 + 回主屏。"""
        emit_live("system", "场景恢复：正在清空后台应用...")
        logger.info("[tools:recover_scene] serial=%s", serial)
        try:
            detail = await asyncio.to_thread(adb_service.recover_scene, serial)
            stopped = (detail.get("clear_background") or {}).get("force_stopped_count", 0)
            message = f"场景恢复完成：已结束 {stopped} 个第三方应用并返回主屏幕"
            emit_live("system", message, detail=detail)
            logger.info("[tools:recover_scene] %s", message)
            return {"success": True, "message": message, "detail": detail}
        except Exception as exc:
            message = f"场景恢复失败: {exc}"
            logger.warning("[tools:recover_scene] %s", message)
            emit_live("system", message, detail={"error": str(exc)})
            return {"success": False, "message": message, "detail": {"error": str(exc)}}


agent_tools = AgentTools()
