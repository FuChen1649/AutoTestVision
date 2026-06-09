import base64
from io import BytesIO

from PIL import Image, ImageDraw

from app.agent_test_service.schemas import ActionIntent


def _load_image(data_url: str) -> Image.Image:
    payload = data_url.split(",", 1)[-1]
    with Image.open(BytesIO(base64.b64decode(payload))) as image:
        return image.convert("RGBA")


def _to_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def annotate_before_image(image_data_url: str, intent: ActionIntent) -> str:
    if intent.action == "skip" or intent.x is None or intent.y is None:
        return image_data_url

    image = _load_image(image_data_url)
    draw = ImageDraw.Draw(image)

    if intent.action in {"tap", "long_press"}:
        radius = 28 if intent.action == "long_press" else 18
        x, y = intent.x, intent.y
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(59, 130, 246, 255),
            width=4,
        )
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(59, 130, 246, 220))
        label = "长按" if intent.action == "long_press" else "点击"
        draw.text((x + radius + 6, y - 10), label, fill=(59, 130, 246, 255))

    elif intent.action == "swipe" and intent.x2 is not None and intent.y2 is not None:
        draw.line((intent.x, intent.y, intent.x2, intent.y2), fill=(59, 130, 246, 255), width=5)
        draw.ellipse((intent.x - 8, intent.y - 8, intent.x + 8, intent.y + 8), fill=(34, 197, 94, 230))
        draw.ellipse((intent.x2 - 8, intent.y2 - 8, intent.x2 + 8, intent.y2 + 8), fill=(239, 68, 68, 230))
        draw.text((intent.x + 10, intent.y - 18), "滑动", fill=(59, 130, 246, 255))

    return _to_data_url(image)
