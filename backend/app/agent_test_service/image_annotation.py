import base64
from io import BytesIO

from PIL import Image, ImageDraw

from app.agent_test_service.schemas import ActionIntent

_TAP_OUTLINE = (255, 0, 100, 255)
_TAP_CENTER = (255, 230, 0, 240)
_LONG_PRESS_OUTLINE = (255, 120, 0, 255)
_SWIPE_LINE = (0, 255, 180, 255)
_SWIPE_START = (0, 255, 120, 255)
_SWIPE_END = (255, 50, 50, 255)
_FRAME_OUTER = (255, 40, 120, 255)
_FRAME_INNER = (255, 230, 0, 255)
_LABEL_FILL = (255, 255, 255, 255)
_LABEL_SHADOW = (0, 0, 0, 200)


def _load_image(data_url: str) -> Image.Image:
    payload = data_url.split(",", 1)[-1]
    with Image.open(BytesIO(base64.b64decode(payload))) as image:
        return image.convert("RGBA")


def _to_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _draw_crosshair(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int, int]) -> None:
    draw.line((x - size, y, x + size, y), fill=color, width=3)
    draw.line((x, y - size, x, y + size), fill=color, width=3)


def _draw_frame_box(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    label: str = "目标",
) -> None:
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    outer = 5 if min(width, height) > 40 else 4
    draw.rectangle((left, top, right, bottom), outline=_FRAME_OUTER, width=outer)
    inset = outer + 1
    draw.rectangle(
        (left + inset, top + inset, right - inset, bottom - inset),
        outline=_FRAME_INNER,
        width=2,
    )
    tick = min(18, max(8, min(width, height) // 4))
    for x0, y0, x1, y1 in (
        (left, top, left + tick, top),
        (left, top, left, top + tick),
        (right - tick, top, right, top),
        (right, top, right, top + tick),
        (left, bottom, left + tick, bottom),
        (left, bottom - tick, left, bottom),
        (right - tick, bottom, right, bottom),
        (right, bottom - tick, right, bottom),
    ):
        draw.line((x0, y0, x1, y1), fill=_FRAME_INNER, width=3)

    text_x = left
    text_y = max(0, top - 20)
    draw.text((text_x + 1, text_y + 1), label, fill=_LABEL_SHADOW)
    draw.text((text_x, text_y), label, fill=_LABEL_FILL)


def annotate_before_image(
    image_data_url: str,
    intent: ActionIntent,
    *,
    highlight_rect: tuple[int, int, int, int] | None = None,
    frame_only: bool = False,
) -> str:
    if intent.action == "skip":
        return image_data_url
    if frame_only and highlight_rect:
        image = _load_image(image_data_url)
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = highlight_rect
        label = "长按" if intent.action == "long_press" else "点击"
        _draw_frame_box(draw, left, top, right, bottom, label=label)
        return _to_data_url(image)

    if intent.x is None or intent.y is None:
        return image_data_url

    image = _load_image(image_data_url)
    draw = ImageDraw.Draw(image)

    if intent.action in {"tap", "long_press"}:
        radius = 32 if intent.action == "long_press" else 24
        x, y = intent.x, intent.y
        outline = _LONG_PRESS_OUTLINE if intent.action == "long_press" else _TAP_OUTLINE
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=outline,
            width=6,
        )
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=_TAP_CENTER)
        _draw_crosshair(draw, x, y, radius + 6, outline)
        label = "长按" if intent.action == "long_press" else "点击"
        draw.text((x + radius + 8, y - 14), label, fill=_LABEL_FILL)

    elif intent.action == "swipe" and intent.x2 is not None and intent.y2 is not None:
        draw.line((intent.x, intent.y, intent.x2, intent.y2), fill=_SWIPE_LINE, width=7)
        draw.ellipse((intent.x - 10, intent.y - 10, intent.x + 10, intent.y + 10), fill=_SWIPE_START)
        draw.ellipse((intent.x2 - 10, intent.y2 - 10, intent.x2 + 10, intent.y2 + 10), fill=_SWIPE_END)
        _draw_crosshair(draw, intent.x, intent.y, 16, _SWIPE_START)
        _draw_crosshair(draw, intent.x2, intent.y2, 16, _SWIPE_END)
        draw.text((intent.x + 12, intent.y - 20), "滑动", fill=_LABEL_FILL)

    return _to_data_url(image)
