"""模型坐标 → 截图像素 → 设备触控坐标的换算。"""

from __future__ import annotations

import base64
import logging
from io import BytesIO

from PIL import Image

from app.agent_test_service.schemas import ActionIntent
from app.config import settings

logger = logging.getLogger(__name__)

# Qwen-VL / Gemma 3·4 等视觉 grounding 普遍输出 0-1000 相对坐标（相对截图宽高）
_NORMALIZED_1000_MODEL_MARKERS = (
    "qwen3",
    "qwen2.5",
    "qwen2-vl",
    "qwen3-vl",
    "qwen2.5-vl",
    "gemma3",
    "gemma4",
    "gemma-3",
    "gemma-4",
)


def decode_image_size(image_data_url: str) -> tuple[int, int]:
    payload = image_data_url.split(",", 1)[-1]
    with Image.open(BytesIO(base64.b64decode(payload))) as image:
        return image.size


def uses_normalized_1000_coords(*, provider: str | None = None, model_name: str | None = None) -> bool:
    model = (model_name or "").lower()
    if not model:
        if provider == "online":
            model = (settings.agent_llm_model or "").lower()
        elif provider == "local":
            model = (settings.agent_local_model or "").lower()
    return any(marker in model for marker in _NORMALIZED_1000_MODEL_MARKERS)


def uses_qwen_normalized_coords(*, provider: str | None = None, model_name: str | None = None) -> bool:
    """兼容旧名；现涵盖 Qwen-VL 与 Gemma 3/4 等 0-1000 坐标系模型。"""
    return uses_normalized_1000_coords(provider=provider, model_name=model_name)


def model_coords_to_image_pixels(
    intent: ActionIntent,
    image_width: int,
    image_height: int,
    *,
    provider: str | None = None,
    model_name: str | None = None,
) -> ActionIntent:
    """将模型输出坐标转换为截图像素坐标。"""
    if intent.action == "skip" or intent.x is None or intent.y is None:
        return intent
    if image_width <= 0 or image_height <= 0:
        return intent

    mapped = intent.model_copy(deep=True)
    raw_x, raw_y = intent.x, intent.y

    if uses_normalized_1000_coords(provider=provider, model_name=model_name):
        mapped.x = round(raw_x / 1000 * image_width)
        mapped.y = round(raw_y / 1000 * image_height)
        if mapped.x2 is not None:
            mapped.x2 = round(mapped.x2 / 1000 * image_width)
        if mapped.y2 is not None:
            mapped.y2 = round(mapped.y2 / 1000 * image_height)
        logger.info(
            "[coordinate_mapper] 0-1000→像素 raw=(%s,%s) image=%dx%d pixel=(%s,%s)",
            raw_x,
            raw_y,
            image_width,
            image_height,
            mapped.x,
            mapped.y,
        )
    else:
        logger.debug(
            "[coordinate_mapper] 按像素坐标使用 model=(%s,%s) image=%dx%d",
            raw_x,
            raw_y,
            image_width,
            image_height,
        )

    mapped.x = max(0, min(mapped.x, image_width - 1))
    mapped.y = max(0, min(mapped.y, image_height - 1))
    if mapped.x2 is not None:
        mapped.x2 = max(0, min(mapped.x2, image_width - 1))
    if mapped.y2 is not None:
        mapped.y2 = max(0, min(mapped.y2, image_height - 1))
    return mapped


def image_pixels_to_device(
    intent: ActionIntent,
    image_width: int,
    image_height: int,
    device_width: int,
    device_height: int,
) -> ActionIntent:
    """截图像素坐标映射到设备触控坐标（尺寸不一致时才缩放）。"""
    if intent.action == "skip":
        return intent
    if image_width <= 0 or image_height <= 0:
        return intent
    if image_width == device_width and image_height == device_height:
        return intent

    scale_x = device_width / image_width
    scale_y = device_height / image_height
    mapped = intent.model_copy(deep=True)
    if mapped.x is not None:
        mapped.x = round(mapped.x * scale_x)
    if mapped.y is not None:
        mapped.y = round(mapped.y * scale_y)
    if mapped.x2 is not None:
        mapped.x2 = round(mapped.x2 * scale_x)
    if mapped.y2 is not None:
        mapped.y2 = round(mapped.y2 * scale_y)

    logger.info(
        "[coordinate_mapper] 截图→设备 image=%dx%d device=%dx%d tap=(%s,%s)",
        image_width,
        image_height,
        device_width,
        device_height,
        mapped.x,
        mapped.y,
    )
    return mapped


def resolve_intent_coordinates(
    intent: ActionIntent,
    image_data_url: str,
    *,
    declared_width: int,
    declared_height: int,
    device_width: int,
    device_height: int,
    provider: str | None = None,
    model_name: str | None = None,
) -> tuple[ActionIntent, int, int]:
    """完整换算：模型坐标 → 截图像素 → 设备触控。返回 (intent, image_w, image_h)。"""
    try:
        image_width, image_height = decode_image_size(image_data_url)
    except Exception as exc:
        logger.warning("[coordinate_mapper] 解码截图尺寸失败，使用声明尺寸: %s", exc)
        image_width, image_height = declared_width, declared_height

    if (image_width, image_height) != (declared_width, declared_height):
        logger.warning(
            "[coordinate_mapper] 截图实际尺寸与声明不一致 declared=%dx%d actual=%dx%d",
            declared_width,
            declared_height,
            image_width,
            image_height,
        )

    pixel_intent = model_coords_to_image_pixels(
        intent,
        image_width,
        image_height,
        provider=provider,
        model_name=model_name,
    )
    device_intent = image_pixels_to_device(
        pixel_intent,
        image_width,
        image_height,
        device_width,
        device_height,
    )
    return device_intent, image_width, image_height
