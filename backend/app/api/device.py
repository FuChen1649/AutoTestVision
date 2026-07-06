import asyncio
import base64
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from app.schemas.device import (
    AppInfo,
    AppPermissionInfo,
    DeviceInfo,
    DeviceKeyRequest,
    LongPressRequest,
    PermissionApplyRequest,
    PermissionApplyResult,
    SwipeRequest,
    TapRequest,
)
from app.services.adb import adb_service

router = APIRouter(prefix="/device", tags=["device"])


@router.get("/list", response_model=list[DeviceInfo])
async def list_devices() -> list[DeviceInfo]:
    try:
        devices = await asyncio.to_thread(adb_service.list_devices)
        if not devices:
            logger.info("device/list 返回空列表（ADB 未检测到就绪设备）")
        return devices
    except RuntimeError as exc:
        logger.warning("device/list 失败: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/select/{serial}")
async def select_device(serial: str) -> dict[str, str]:
    devices = await asyncio.to_thread(adb_service.list_devices)
    if not any(device.serial == serial for device in devices):
        raise HTTPException(status_code=404, detail="设备未连接")
    adb_service.set_active_device(serial)
    return {"serial": serial}


@router.get("/screenshot")
async def get_screenshot(serial: str | None = None) -> dict[str, str | int]:
    try:
        image_bytes = await adb_service.capture_screen(serial=serial)
        width, height = adb_service.get_image_size(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return {
            "image": f"data:image/png;base64,{encoded}",
            "width": width,
            "height": height,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/tap")
async def tap_device(payload: TapRequest) -> dict[str, str]:
    try:
        await adb_service.tap(payload.x, payload.y, serial=payload.serial)
        return {"status": "ok"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/apps", response_model=list[AppInfo])
async def list_apps(serial: str | None = None) -> list[AppInfo]:
    try:
        return await asyncio.to_thread(adb_service.list_apps, serial)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/apps/{package}/permissions", response_model=list[AppPermissionInfo])
async def get_app_permissions(package: str, serial: str | None = None) -> list[AppPermissionInfo]:
    try:
        return await asyncio.to_thread(adb_service.get_app_permissions, package, serial)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/apps/{package}/permissions/apply", response_model=PermissionApplyResult)
async def apply_app_permissions(
    package: str, payload: PermissionApplyRequest
) -> PermissionApplyResult:
    try:
        return await asyncio.to_thread(
            adb_service.apply_app_permissions,
            package,
            payload.selected_permissions,
            payload.serial,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/long-press")
async def long_press_device(payload: LongPressRequest) -> dict[str, str]:
    try:
        await adb_service.long_press(
            payload.x, payload.y, duration_ms=payload.duration_ms, serial=payload.serial
        )
        return {"status": "ok"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/swipe")
async def swipe_device(payload: SwipeRequest) -> dict[str, str]:
    try:
        await adb_service.swipe(
            payload.x1,
            payload.y1,
            payload.x2,
            payload.y2,
            duration_ms=payload.duration_ms,
            serial=payload.serial,
        )
        return {"status": "ok"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/key")
async def press_device_key(payload: DeviceKeyRequest) -> dict[str, str]:
    try:
        if payload.key == "back":
            await asyncio.to_thread(adb_service.press_back_key, payload.serial)
        elif payload.key == "home":
            await asyncio.to_thread(adb_service.press_home_key, payload.serial)
        else:
            await asyncio.to_thread(adb_service.press_recents_key, payload.serial)
        return {"status": "ok"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.websocket("/stream")
async def stream_screen(websocket: WebSocket, serial: str | None = None, fps: int = 5) -> None:
    await websocket.accept()
    interval = max(1.0 / min(max(fps, 1), 15), 0.05)

    try:
        while True:
            try:
                image_bytes = await adb_service.capture_screen(serial=serial)
                width, height = adb_service.get_image_size(image_bytes)
                encoded = base64.b64encode(image_bytes).decode("ascii")
                await websocket.send_json(
                    {
                        "type": "frame",
                        "image": f"data:image/png;base64,{encoded}",
                        "width": width,
                        "height": height,
                    }
                )
            except RuntimeError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})

            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return
