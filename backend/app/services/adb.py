import asyncio
import logging
import re
import subprocess
import time
from io import BytesIO

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)
from app.schemas.device import AppInfo, AppPermissionInfo, DeviceInfo, PermissionApplyResult
from app.services.app_permissions import (
    COMMON_APP_PRIORITY,
    SYSTEM_APP_PRIORITY,
    app_sort_key,
    package_label,
    parse_package_permissions,
)


class AdbService:
    def __init__(self, adb_path: str | None = None) -> None:
        self.adb_path = adb_path or settings.adb_path
        self._active_serial: str | None = None

    def _run(
        self, *args: str, serial: str | None = None, timeout: int = 15
    ) -> subprocess.CompletedProcess[bytes]:
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)
        try:
            return subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"adb 命令超时: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"未找到 adb 可执行文件 ({self.adb_path})，请确认 ADB 已安装并在 PATH 中"
            ) from exc

    async def _run_async(self, *args: str, serial: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return await asyncio.to_thread(self._run, *args, serial=serial)

    def _parse_device_lines(self, output: str) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []

        for line in output.strip().splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue

            serial = parts[0]
            status = parts[1]
            if status != "device":
                logger.info("跳过非就绪设备 %s (status=%s)", serial, status)
                continue

            props = {item.split(":", 1)[0]: item.split(":", 1)[1] for item in parts[2:] if ":" in item}
            width, height = self._get_screen_size(serial)
            devices.append(
                DeviceInfo(
                    serial=serial,
                    model=props.get("model", ""),
                    product=props.get("product", ""),
                    screen_width=width,
                    screen_height=height,
                    connected=True,
                )
            )

        return devices

    def list_devices(self) -> list[DeviceInfo]:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                result = self._run("devices", "-l", timeout=8)
                stderr = result.stderr.decode("utf-8", errors="ignore").strip()
                if result.returncode != 0:
                    raise RuntimeError(stderr or f"adb devices 失败 (code={result.returncode})")

                output = result.stdout.decode("utf-8", errors="ignore")
                devices = self._parse_device_lines(output)
                if devices:
                    if not self._active_serial or not any(
                        device.serial == self._active_serial for device in devices
                    ):
                        self._active_serial = devices[0].serial
                    logger.debug("检测到 %d 台设备", len(devices))
                    return devices

                if attempt == 0:
                    logger.info("首次未检测到设备，尝试启动 adb server")
                    self._run("start-server", timeout=10)
                elif attempt == 1:
                    logger.info("仍未检测到设备，等待 ADB 就绪后重试")
            except Exception as exc:
                last_error = exc
                logger.warning("list_devices 第 %d 次尝试失败: %s", attempt + 1, exc)
                if attempt == 0:
                    try:
                        self._run("start-server", timeout=10)
                    except Exception as start_exc:
                        logger.warning("adb start-server 失败: %s", start_exc)

            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))

        if last_error:
            raise last_error
        return []

    def _get_screen_size(self, serial: str) -> tuple[int, int]:
        try:
            result = self._run("shell", "wm", "size", serial=serial, timeout=5)
            output = result.stdout.decode("utf-8", errors="ignore")
            match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
            match = re.search(r"Override size:\s*(\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception as exc:
            logger.warning("获取屏幕尺寸失败 serial=%s: %s", serial, exc)
        return 1080, 1920

    def set_active_device(self, serial: str) -> None:
        self._active_serial = serial

    def get_active_serial(self) -> str | None:
        return self._active_serial

    async def capture_screen(self, serial: str | None = None) -> bytes:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        result = await self._run_async("exec-out", "screencap", "-p", serial=target)
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "截屏失败")
        return result.stdout

    async def tap(self, x: int, y: int, serial: str | None = None) -> None:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        result = await self._run_async("shell", "input", "tap", str(x), str(y), serial=target)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "点击失败")

    async def long_press(self, x: int, y: int, duration_ms: int = 800, serial: str | None = None) -> None:
        await self.swipe(x, y, x, y, duration_ms=duration_ms, serial=serial)

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, serial: str | None = None
    ) -> None:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        result = await self._run_async(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
            serial=target,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "滑动失败")

    def get_image_size(self, image_bytes: bytes) -> tuple[int, int]:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.size

    def _decode(self, result: subprocess.CompletedProcess[bytes]) -> str:
        return result.stdout.decode("utf-8", errors="ignore")

    def _list_package_names(self, serial: str) -> set[str]:
        packages: set[str] = set()
        for flag in ("-3", "-s"):
            result = self._run("shell", "pm", "list", "packages", flag, serial=serial, timeout=30)
            for line in self._decode(result).splitlines():
                if line.startswith("package:"):
                    packages.add(line.split(":", 1)[1].strip())
        return packages

    def _app_category(self, package: str) -> str:
        if package in SYSTEM_APP_PRIORITY or package.startswith(("com.android.", "com.google.android.", "android.")):
            return "system"
        if package in COMMON_APP_PRIORITY:
            return "common"
        return "other"

    def list_apps(self, serial: str | None = None) -> list[AppInfo]:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        package_names = self._list_package_names(target)
        apps: list[AppInfo] = []

        for package in sorted(package_names, key=app_sort_key):
            apps.append(
                AppInfo(
                    package=package,
                    label=package_label(package),
                    category=self._app_category(package),
                )
            )

        return apps

    def get_app_permissions(self, package: str, serial: str | None = None) -> list[AppPermissionInfo]:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        dump_result = self._run("shell", "dumpsys", "package", package, serial=target, timeout=20)
        dump_text = self._decode(dump_result)
        if "Unable to find package" in dump_text:
            raise RuntimeError("应用不存在")

        return [
            AppPermissionInfo(
                name=item.name,
                label=item.label,
                granted=item.granted,
                revocable=item.revocable,
                group=item.group,
            )
            for item in parse_package_permissions(dump_text)
        ]

    def apply_app_permissions(
        self, package: str, selected_permissions: list[str], serial: str | None = None
    ) -> PermissionApplyResult:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")

        current = self.get_app_permissions(package, serial=target)
        selected_set = set(selected_permissions)
        granted: list[str] = []
        revoked: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        for permission in current:
            if not permission.revocable:
                if permission.name not in selected_set:
                    skipped.append(permission.name)
                continue

            should_grant = permission.name in selected_set
            currently_granted = permission.granted is True

            if should_grant and not currently_granted:
                result = self._run(
                    "shell", "pm", "grant", package, permission.name, serial=target, timeout=10
                )
                if result.returncode == 0:
                    granted.append(permission.name)
                else:
                    errors.append(
                        f"授予 {permission.name} 失败: {result.stderr.decode('utf-8', errors='ignore')}"
                    )
            elif not should_grant and currently_granted:
                result = self._run(
                    "shell", "pm", "revoke", package, permission.name, serial=target, timeout=10
                )
                if result.returncode == 0:
                    revoked.append(permission.name)
                else:
                    errors.append(
                        f"撤销 {permission.name} 失败: {result.stderr.decode('utf-8', errors='ignore')}"
                    )

        return PermissionApplyResult(
            package=package,
            granted=granted,
            revoked=revoked,
            skipped=skipped,
            errors=errors,
        )


adb_service = AdbService()
