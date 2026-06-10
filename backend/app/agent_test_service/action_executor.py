import asyncio
import base64

from app.agent_test_service.agent_logger import get_agent_logger
from app.agent_test_service.coordinate_mapper import image_pixels_to_device
from app.agent_test_service.schemas import ActionIntent
from app.services.adb import adb_service

logger = get_agent_logger()


class ActionExecutor:
    async def capture_screen(self, serial: str | None) -> tuple[str, int, int]:
        logger.debug("[action_executor] 截图 serial=%s", serial)
        image_bytes = await adb_service.capture_screen(serial=serial)
        width, height = adb_service.get_image_size(image_bytes)
        logger.debug("[action_executor] 截图完成 %dx%d", width, height)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}", width, height

    async def get_device_screen_size(self, serial: str | None) -> tuple[int, int]:
        return await asyncio.to_thread(adb_service.get_screen_size, serial)

    def map_coordinates(
        self,
        intent: ActionIntent,
        image_width: int,
        image_height: int,
        device_width: int,
        device_height: int,
    ) -> ActionIntent:
        return image_pixels_to_device(intent, image_width, image_height, device_width, device_height)

    async def execute(self, intent: ActionIntent, serial: str | None) -> ActionIntent:
        if intent.action == "skip":
            logger.info("[action_executor] 跳过操作 serial=%s", serial)
            return intent

        if intent.x is None or intent.y is None:
            logger.error("[action_executor] 执行坐标缺失 action=%s", intent.action)
            raise RuntimeError("执行坐标缺失")

        logger.info(
            "[action_executor] 执行 action=%s pos=(%s,%s) serial=%s",
            intent.action,
            intent.x,
            intent.y,
            serial,
        )
        if intent.action == "tap":
            await adb_service.tap(intent.x, intent.y, serial=serial)
        elif intent.action == "long_press":
            await adb_service.long_press(
                intent.x, intent.y, duration_ms=intent.duration_ms, serial=serial
            )
        elif intent.action == "swipe":
            if intent.x2 is None or intent.y2 is None:
                raise RuntimeError("滑动终点坐标缺失")
            await adb_service.swipe(
                intent.x,
                intent.y,
                intent.x2,
                intent.y2,
                duration_ms=intent.duration_ms,
                serial=serial,
            )
        else:
            raise RuntimeError(f"不支持的操作类型: {intent.action}")

        return intent


action_executor = ActionExecutor()
