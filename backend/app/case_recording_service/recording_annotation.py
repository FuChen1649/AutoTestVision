from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageDraw

from app.models.case_recording import CaseRecordingEvent

_RED = (255, 0, 0, 255)
_BORDER = 4
_DEFAULT_HALF = 48


def _load_image(data_url: str) -> Image.Image:
    payload = data_url.split(",", 1)[-1]
    with Image.open(BytesIO(base64.b64decode(payload))) as image:
        return image.convert("RGBA")


def _to_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _clamp_rect(
    cx: int, cy: int, half_w: int, half_h: int, img_w: int, img_h: int
) -> tuple[int, int, int, int]:
    left = max(0, cx - half_w)
    top = max(0, cy - half_h)
    right = min(img_w, cx + half_w)
    bottom = min(img_h, cy + half_h)
    return left, top, right, bottom


def _draw_red_box(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int) -> None:
    for offset in range(_BORDER):
        draw.rectangle(
            (left - offset, top - offset, right + offset, bottom + offset),
            outline=_RED,
            width=1,
        )


def annotate_recording_display(
    image_data_url: str,
    event: CaseRecordingEvent,
) -> tuple[str, int | None, int | None, int | None, int | None]:
    """在截图上用红色边框标出操作区域，返回标注图与选区 (x, y, w, h)。"""
    if event.action_type == "key" or event.x is None or event.y is None:
        return image_data_url, event.x, event.y, None, None

    image = _load_image(image_data_url)
    draw = ImageDraw.Draw(image)
    img_w, img_h = image.size

    if event.action_type == "swipe" and event.x2 is not None and event.y2 is not None:
        start = _clamp_rect(event.x, event.y, _DEFAULT_HALF, _DEFAULT_HALF, img_w, img_h)
        end = _clamp_rect(event.x2, event.y2, _DEFAULT_HALF, _DEFAULT_HALF, img_w, img_h)
        _draw_red_box(draw, *start)
        _draw_red_box(draw, *end)
        draw.line((event.x, event.y, event.x2, event.y2), fill=_RED, width=3)
        sel_x, sel_y = start[0], start[1]
        sel_w, sel_h = start[2] - start[0], start[3] - start[1]
        return _to_data_url(image), sel_x, sel_y, sel_w, sel_h

    half = 56 if event.action_type == "long_press" else _DEFAULT_HALF
    left, top, right, bottom = _clamp_rect(event.x, event.y, half, half, img_w, img_h)
    _draw_red_box(draw, left, top, right, bottom)
    sel_w = max(right - left, 1)
    sel_h = max(bottom - top, 1)
    return _to_data_url(image), left, top, sel_w, sel_h


def display_image_filename(step_order: int) -> str:
    return f"event_{step_order:04d}_display.png"
