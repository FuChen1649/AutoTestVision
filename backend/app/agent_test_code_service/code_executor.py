from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

from app.agent_test_code_service.schemas import GeneratedStepCode
from app.agent_test_service.agent_logger import get_agent_logger
from app.config import settings

logger = get_agent_logger()


def _run_u2_inline(code_line: str, serial: str) -> tuple[int, str]:
    import uiautomator2 as u2

    device = u2.connect(serial)
    try:
        namespace = {"d": device, "__builtins__": __builtins__}
        exec(compile(code_line, "<agent_code>", "exec"), namespace)
        return 0, f"已执行: {code_line}\n设备: {serial}"
    finally:
        try:
            device.reset_uiautomator()
        except Exception:
            pass


class CodeExecutor:
    async def execute(
        self, code_line: str, serial: str, test_file: Path | None = None
    ) -> GeneratedStepCode:
        """进程内执行 u2 代码（避免子进程 pytest 与后端 ADB 争用）。"""
        if not serial:
            raise RuntimeError("未连接设备，无法执行 uiautomator2 代码")
        if not code_line.strip():
            raise RuntimeError("生成的代码为空")

        logger.info("[code_executor] 进程内执行 serial=%s code=%s", serial, code_line)
        try:
            exit_code, output = await asyncio.to_thread(_run_u2_inline, code_line, serial)
        except Exception as exc:
            exit_code = 1
            output = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.warning("[code_executor] 执行失败: %s", exc)

        logger.info("[code_executor] inline exit=%d output_len=%d", exit_code, len(output))

        if settings.agent_code_run_pytest_subprocess and test_file and exit_code == 0:
            pytest_result = await self.run_pytest(test_file)
            if pytest_result.pytest_exit_code != 0:
                output = f"{output}\n\n--- pytest 校验 ---\n{pytest_result.execution_output or ''}"
                exit_code = pytest_result.pytest_exit_code or 1

        return GeneratedStepCode(
            code_line=code_line,
            execution_output=output,
            pytest_exit_code=exit_code,
            reasoning="代码执行成功" if exit_code == 0 else "代码执行失败",
            confidence=1.0 if exit_code == 0 else 0.0,
        )

    async def run_pytest(self, test_file: Path) -> GeneratedStepCode:
        cmd = [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"]
        logger.info("[code_executor] pytest %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(test_file.parent),
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=settings.agent_code_pytest_timeout_sec
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"pytest 超时（>{settings.agent_code_pytest_timeout_sec}s）")

        output = stdout.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0
        logger.info("[code_executor] pytest exit=%d output_len=%d", exit_code, len(output))
        return GeneratedStepCode(
            code_line="",
            execution_output=output,
            pytest_exit_code=exit_code,
            reasoning="pytest 执行成功" if exit_code == 0 else "pytest 执行失败",
            confidence=1.0 if exit_code == 0 else 0.0,
        )


code_executor = CodeExecutor()
