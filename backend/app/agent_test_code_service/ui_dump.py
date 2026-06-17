"""获取界面 UI XML：优先 u2（与代码执行共用 ATX），adb dump 作备选。"""

from __future__ import annotations

import asyncio
import time

from app.agent_test_service.agent_logger import get_agent_logger
from app.services.adb import adb_service

logger = get_agent_logger()


def _dump_via_u2(serial: str, *, max_chars: int) -> str:
    import uiautomator2 as u2

    device = u2.connect(serial)
    xml = device.dump_hierarchy(compressed=False)
    if not xml or len(xml) < 50:
        raise RuntimeError("u2 dump_hierarchy 返回内容过短")
    if len(xml) > max_chars:
        return xml[:max_chars] + "\n<!-- truncated -->"
    return xml


def dump_ui_xml_sync(serial: str | None, *, max_chars: int = 120_000) -> str:
    if not serial:
        raise RuntimeError("未连接设备，无法 dump UI")

    errors: list[str] = []

    try:
        xml = _dump_via_u2(serial, max_chars=max_chars)
        logger.debug("[ui_dump] u2 dump 成功 len=%d serial=%s", len(xml), serial)
        return xml
    except Exception as exc:
        errors.append(f"u2: {exc}")
        logger.warning("[ui_dump] u2 dump 失败 serial=%s: %s", serial, exc)

    for attempt in range(3):
        try:
            if attempt:
                time.sleep(0.6 * attempt)
            xml = adb_service.dump_ui_hierarchy(serial, max_chars=max_chars)
            logger.debug("[ui_dump] adb dump 成功 len=%d attempt=%d", len(xml), attempt + 1)
            return xml
        except Exception as exc:
            errors.append(f"adb#{attempt + 1}: {exc}")
            logger.warning("[ui_dump] adb dump 第 %d 次失败: %s", attempt + 1, exc)

    logger.warning("[ui_dump] 全部失败，使用空 XML 继续: %s", "; ".join(errors))
    return ""


async def dump_ui_xml_async(serial: str | None, *, max_chars: int = 120_000) -> str:
    return await asyncio.to_thread(dump_ui_xml_sync, serial, max_chars=max_chars)
