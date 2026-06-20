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

    def get_screen_size(self, serial: str | None = None) -> tuple[int, int]:
        """设备触控/显示逻辑尺寸（wm size）。"""
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")
        return self._get_screen_size(target)

    def dump_ui_hierarchy(self, serial: str | None = None, *, max_chars: int = 120_000) -> str:
        """uiautomator dump 当前界面 XML（带重试）。"""
        target = self._resolve_serial(serial)
        dump_path = "/sdcard/autotest_ui_dump.xml"
        last_error = ""
        for attempt in range(3):
            if attempt:
                time.sleep(0.5 * attempt)
            dump_result = self._run(
                "shell", "uiautomator", "dump", dump_path, serial=target, timeout=25
            )
            if dump_result.returncode == 0:
                cat_result = self._run("shell", "cat", dump_path, serial=target, timeout=15)
                if cat_result.returncode == 0 and cat_result.stdout:
                    xml = cat_result.stdout.decode("utf-8", errors="ignore")
                    if len(xml) > 50:
                        if len(xml) > max_chars:
                            return xml[:max_chars] + "\n<!-- truncated -->"
                        return xml
                last_error = "读取 UI dump 失败"
            else:
                stderr = dump_result.stderr.decode(errors="ignore").strip()
                stdout = dump_result.stdout.decode(errors="ignore").strip()
                last_error = stderr or stdout or f"exit={dump_result.returncode}"
        raise RuntimeError(f"uiautomator dump 失败: {last_error}")

    async def dump_ui_hierarchy_async(self, serial: str | None = None, *, max_chars: int = 120_000) -> str:
        return await asyncio.to_thread(self.dump_ui_hierarchy, serial, max_chars=max_chars)

    def set_active_device(self, serial: str) -> None:
        self._active_serial = serial

    def get_active_serial(self) -> str | None:
        return self._active_serial

    def _resolve_serial(self, serial: str | None) -> str:
        target = serial or self._active_serial
        if not target:
            raise RuntimeError("未连接设备")
        return target

    _RECENTS_CLOSE_LABELS = (
        "close all",
        "clear all",
        "全部关闭",
        "关闭全部",
        "清除全部",
        "全部清除",
        "一键清除",
    )
    _RECENTS_CLEAR_ALL_RESOURCE_IDS = (
        "com.sec.android.app.launcher:id/clear_all",
        "com.android.systemui:id/clear_all",
        "com.miui.home:id/clearAnimView",
    )

    _LAUNCHER_HOME_COMPONENTS = (
        "com.sec.android.app.launcher/.activities.LauncherActivity",
        "com.google.android.apps.nexuslauncher/.NexusLauncherActivity",
        "com.miui.home/.launcher.Launcher",
    )

    def press_back_key(
        self, serial: str | None = None, *, times: int = 1, interval_sec: float = 0.35
    ) -> int:
        """发送 Android BACK 键（KEYCODE_BACK=4）。"""
        if times < 1:
            return 0
        target = self._resolve_serial(serial)
        sent = 0
        for index in range(times):
            result = self._run("shell", "input", "keyevent", "4", serial=target, timeout=5)
            if result.returncode == 0:
                sent += 1
            if index < times - 1:
                time.sleep(interval_sec)
        logger.info("[adb] 已发送 BACK 键 serial=%s times=%d", target, sent)
        return sent

    def press_home_key(
        self, serial: str | None = None, *, times: int = 1, interval_sec: float = 0.35
    ) -> int:
        """发送 Android HOME 键（KEYCODE_HOME=3）。"""
        if times < 1:
            return 0
        target = self._resolve_serial(serial)
        sent = 0
        for index in range(times):
            result = self._run("shell", "input", "keyevent", "3", serial=target, timeout=5)
            if result.returncode == 0:
                sent += 1
            if index < times - 1:
                time.sleep(interval_sec)
        logger.info("[adb] 已发送 HOME 键 serial=%s times=%d", target, sent)
        return sent

    def go_home(self, serial: str | None = None) -> None:
        """通过 Launcher Intent 返回手机主屏幕。"""
        target = self._resolve_serial(serial)
        result = self._run(
            "shell",
            "am",
            "start",
            "-W",
            "-c",
            "android.intent.category.HOME",
            "-a",
            "android.intent.action.MAIN",
            serial=target,
            timeout=15,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(stderr or "返回主屏幕失败")

        for component in self._LAUNCHER_HOME_COMPONENTS:
            comp_result = self._run(
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                component,
                serial=target,
                timeout=15,
            )
            if comp_result.returncode == 0:
                logger.info("[adb] Launcher 主屏 Activity 已拉起 serial=%s component=%s", target, component)
                break

        logger.info("[adb] 已返回主屏幕 serial=%s", target)

    def _stabilize_home_screen(self, serial: str, *, phase: str) -> None:
        """多次 HOME + Launcher Intent，尽量回到默认主屏第一页（非抽屉/非多任务）。"""
        logger.info("[adb] 主屏归位 phase=%s serial=%s", phase, serial)
        self.press_home_key(serial, times=2)
        time.sleep(0.25)
        self.go_home(serial)
        time.sleep(0.25)
        self.press_home_key(serial, times=1)

    def _extract_standard_recent_task_ids(self, recents_dump: str) -> list[int]:
        """从 dumpsys activity recents 解析 type=standard 的 taskId。"""
        task_ids: list[int] = []
        seen: set[int] = set()
        for line in recents_dump.splitlines():
            if "type=standard" not in line:
                continue
            match = re.search(r"#(\d+)\s+type=standard", line)
            if not match:
                continue
            task_id = int(match.group(1))
            if task_id in seen:
                continue
            seen.add(task_id)
            task_ids.append(task_id)
        return task_ids

    def _count_standard_recent_tasks(self, serial: str) -> int:
        result = self._run("shell", "dumpsys", "activity", "recents", serial=serial, timeout=15)
        return len(self._extract_standard_recent_task_ids(self._decode(result)))

    def _remove_recent_tasks_via_stack(self, serial: str) -> tuple[int, list[str]]:
        """逐个 am stack remove，从最近任务列表移除卡片。"""
        result = self._run("shell", "dumpsys", "activity", "recents", serial=serial, timeout=15)
        task_ids = self._extract_standard_recent_task_ids(self._decode(result))
        removed = 0
        errors: list[str] = []
        for task_id in task_ids:
            remove_result = self._run("shell", "am", "stack", "remove", str(task_id), serial=serial, timeout=8)
            if remove_result.returncode == 0:
                removed += 1
            else:
                stderr = remove_result.stderr.decode("utf-8", errors="ignore").strip()
                if stderr:
                    errors.append(f"stack remove {task_id}: {stderr}")
        return removed, errors

    def _remove_recent_tasks_via_service_call(self, serial: str) -> bool:
        """尝试调用 ActivityTaskManager.removeAllVisibleRecentTasks（部分机型有效）。"""
        for code in (21, 23, 31):
            result = self._run(
                "shell", "service", "call", "activity_task", str(code), serial=serial, timeout=10
            )
            if result.returncode == 0:
                return True
        return False

    def _parse_ui_tap_point(self, xml: str) -> tuple[int, int] | None:
        for resource_id in self._RECENTS_CLEAR_ALL_RESOURCE_IDS:
            pattern = (
                rf'resource-id="{re.escape(resource_id)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            )
            match = re.search(pattern, xml)
            if match:
                x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
                return (x1 + x2) // 2, (y1 + y2) // 2

        node_pattern = re.compile(
            r'<node[^>]*?(?:text="([^"]*)"|content-desc="([^"]*)")[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        )
        for match in node_pattern.finditer(xml):
            label = (match.group(1) or match.group(2) or "").strip().lower()
            if not label:
                continue
            if not any(token in label for token in self._RECENTS_CLOSE_LABELS):
                continue
            x1, y1, x2, y2 = (int(match.group(i)) for i in range(3, 7))
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    def _clear_recents_via_ui(self, serial: str) -> bool:
        """打开多任务界面并点击「全部关闭」类按钮（三星/部分 OEM）。"""
        open_result = self._run("shell", "input", "keyevent", "187", serial=serial, timeout=5)
        if open_result.returncode != 0:
            return False
        time.sleep(0.9)

        dump_path = "/sdcard/autotest_recents_dump.xml"
        dump_result = self._run(
            "shell", "uiautomator", "dump", dump_path, serial=serial, timeout=15
        )
        if dump_result.returncode != 0:
            return False

        cat_result = self._run("shell", "cat", dump_path, serial=serial, timeout=10)
        if cat_result.returncode != 0 or not cat_result.stdout:
            return False

        xml = cat_result.stdout.decode("utf-8", errors="ignore")
        tap_point = self._parse_ui_tap_point(xml)
        if not tap_point:
            logger.warning("[adb] 未在最近任务界面找到「全部关闭」按钮 serial=%s", serial)
            self._run("shell", "input", "keyevent", "3", serial=serial, timeout=5)
            return False

        tap_result = self._run(
            "shell",
            "input",
            "tap",
            str(tap_point[0]),
            str(tap_point[1]),
            serial=serial,
            timeout=5,
        )
        time.sleep(0.5)
        # 关闭全部后显式回到主屏，避免停留在多任务或副屏
        self.press_home_key(serial, times=2)
        return tap_result.returncode == 0

    def _clear_recent_tasks(self, serial: str) -> dict[str, object]:
        """从「最近任务」列表移除应用卡片（force-stop 无法做到）。"""
        before = self._count_standard_recent_tasks(serial)
        if before == 0:
            return {"before": 0, "after": 0, "removed_stack": 0, "service_call": False, "ui_clear": False}

        service_ok = self._remove_recent_tasks_via_service_call(serial)
        time.sleep(0.3)
        removed_stack, stack_errors = self._remove_recent_tasks_via_stack(serial)
        after = self._count_standard_recent_tasks(serial)

        ui_clear = False
        if after > 0:
            ui_clear = self._clear_recents_via_ui(serial)
            time.sleep(0.3)
            after = self._count_standard_recent_tasks(serial)

        logger.info(
            "[adb] 最近任务清理 serial=%s before=%d after=%d stack_removed=%d service=%s ui=%s",
            serial,
            before,
            after,
            removed_stack,
            service_ok,
            ui_clear,
        )
        return {
            "before": before,
            "after": after,
            "removed_stack": removed_stack,
            "service_call": service_ok,
            "ui_clear": ui_clear,
            "errors": stack_errors[:10],
        }

    def clear_background_apps(self, serial: str | None = None) -> dict[str, object]:
        """结束后台进程，并从最近任务列表移除应用卡片。"""
        target = self._resolve_serial(serial)
        stopped: list[str] = []
        errors: list[str] = []

        list_result = self._run("shell", "pm", "list", "packages", "-3", serial=target, timeout=30)
        packages = [
            line.split(":", 1)[1].strip()
            for line in self._decode(list_result).splitlines()
            if line.startswith("package:")
        ]

        for package in packages:
            stop_result = self._run("shell", "am", "force-stop", package, serial=target, timeout=8)
            if stop_result.returncode == 0:
                stopped.append(package)
            else:
                stderr = stop_result.stderr.decode("utf-8", errors="ignore").strip()
                if stderr:
                    errors.append(f"{package}: {stderr}")

        kill_result = self._run("shell", "am", "kill-all", serial=target, timeout=15)
        kill_all_ok = kill_result.returncode == 0
        if not kill_all_ok:
            stderr = kill_result.stderr.decode("utf-8", errors="ignore").strip()
            if stderr:
                errors.append(f"kill-all: {stderr}")

        recents_detail = self._clear_recent_tasks(target)
        recents_errors = recents_detail.get("errors", [])
        if isinstance(recents_errors, list):
            errors.extend(str(item) for item in recents_errors)

        logger.info(
            "[adb] 后台清理完成 serial=%s force_stop=%d kill_all=%s recents_after=%s",
            target,
            len(stopped),
            kill_all_ok,
            recents_detail.get("after"),
        )
        return {
            "force_stopped_count": len(stopped),
            "kill_all": kill_all_ok,
            "recents": recents_detail,
            "errors": errors[:20],
        }

    def recover_scene(self, serial: str | None = None) -> dict[str, object]:
        """场景恢复：先归位主屏，再清后台，最后再次归位主屏。"""
        target = self._resolve_serial(serial)
        logger.info("[adb] 场景恢复开始 serial=%s", target)

        # 1) 先按 HOME，退出应用/抽屉/副屏
        self.press_home_key(target, times=2)
        time.sleep(0.3)

        # 2) 再通过 Launcher Intent 拉回主屏 Activity
        self.go_home(target)
        time.sleep(0.3)
        self.press_home_key(target, times=1)

        # 3) 清理后台与最近任务（可能短暂打开多任务 UI）
        clear_detail = self.clear_background_apps(target)

        # 4) 清理后再次归位，保证 Case 从同一初始主屏开始
        self._stabilize_home_screen(target, phase="after_clear")

        logger.info("[adb] 场景恢复完成 serial=%s", target)
        return {"clear_background": clear_detail, "home": True, "home_stabilized": True}

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
