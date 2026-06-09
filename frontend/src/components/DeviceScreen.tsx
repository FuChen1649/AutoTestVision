import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, createScreenStream } from "../api/client";
import AppPermissionControls from "./AppPermissionControls";
import type { DeviceInfo, ScreenFrame } from "../types";

interface DeviceScreenProps {
  devices: DeviceInfo[];
  selectedSerial: string | null;
  onSelectDevice: (serial: string) => void;
  onPermissionPresetAdded: () => void;
}

interface ViewportSize {
  width: number;
  height: number;
}

interface DisplayRect {
  offsetX: number;
  offsetY: number;
  width: number;
  height: number;
}

interface PointerState {
  clientX: number;
  clientY: number;
  deviceX: number;
  deviceY: number;
  startedAt: number;
}

const TAP_THRESHOLD_PX = 8;
const LONG_PRESS_TRIGGER_MS = 500;
const LONG_PRESS_DURATION_MS = 800;

export default function DeviceScreen({
  devices,
  selectedSerial,
  onSelectDevice,
  onPermissionPresetAdded,
}: DeviceScreenProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latestFrameRef = useRef<ScreenFrame | null>(null);
  const frameImageRef = useRef<HTMLImageElement | null>(null);
  const frameImageSrcRef = useRef<string | null>(null);
  const viewportSizeRef = useRef<ViewportSize>({ width: 0, height: 0 });
  const deviceSizeRef = useRef({ width: 0, height: 0 });
  const displayRectRef = useRef<DisplayRect>({ offsetX: 0, offsetY: 0, width: 0, height: 0 });
  const pointerRef = useRef<PointerState | null>(null);
  const dragCurrentRef = useRef<{ x: number; y: number } | null>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const longPressTriggeredRef = useRef(false);
  const holdProgressRef = useRef(0);
  const holdAnimFrameRef = useRef<number | null>(null);
  const selectedSerialRef = useRef<string | null>(selectedSerial);

  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permissionMessage, setPermissionMessage] = useState<string | null>(null);
  const [viewportSize, setViewportSize] = useState<ViewportSize>({ width: 0, height: 0 });

  useEffect(() => {
    selectedSerialRef.current = selectedSerial;
  }, [selectedSerial]);

  const clearLongPressTimer = useCallback(() => {
    if (longPressTimerRef.current !== null) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    if (holdAnimFrameRef.current !== null) {
      window.cancelAnimationFrame(holdAnimFrameRef.current);
      holdAnimFrameRef.current = null;
    }
    holdProgressRef.current = 0;
  }, []);

  const resetPointerState = useCallback(() => {
    clearLongPressTimer();
    pointerRef.current = null;
    dragCurrentRef.current = null;
    longPressTriggeredRef.current = false;
    holdProgressRef.current = 0;
  }, [clearLongPressTimer]);

  const renderToCanvas = useCallback((dragTo?: { x: number; y: number } | null) => {
    const canvas = canvasRef.current;
    const frame = latestFrameRef.current;
    const image = frameImageRef.current;
    const viewport = viewportSizeRef.current;

    if (!canvas || !frame?.width || !frame.height || !image || viewport.width <= 0 || viewport.height <= 0) {
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * dpr);
    canvas.height = Math.floor(viewport.height * dpr);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, viewport.width, viewport.height);
    ctx.fillStyle = "#111827";
    ctx.fillRect(0, 0, viewport.width, viewport.height);

    const scale = Math.min(viewport.width / frame.width, viewport.height / frame.height);
    const displayWidth = Math.floor(frame.width * scale);
    const displayHeight = Math.floor(frame.height * scale);
    const offsetX = Math.floor((viewport.width - displayWidth) / 2);
    const offsetY = Math.floor((viewport.height - displayHeight) / 2);

    ctx.drawImage(image, offsetX, offsetY, displayWidth, displayHeight);

    deviceSizeRef.current = { width: frame.width, height: frame.height };
    displayRectRef.current = { offsetX, offsetY, width: displayWidth, height: displayHeight };

    const pointer = pointerRef.current;
    const dragPoint = dragTo ?? dragCurrentRef.current;
    if (pointer && dragPoint) {
      const rect = canvas.getBoundingClientRect();
      const startX = pointer.clientX - rect.left;
      const startY = pointer.clientY - rect.top;
      const endX = dragPoint.x - rect.left;
      const endY = dragPoint.y - rect.top;
      const displayDistance = Math.hypot(endX - startX, endY - startY);

      if (displayDistance > TAP_THRESHOLD_PX) {
        ctx.strokeStyle = "rgba(59, 130, 246, 0.9)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.stroke();
      }

      if (longPressTriggeredRef.current) {
        ctx.strokeStyle = "rgba(34, 197, 94, 0.95)";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(startX, startY, 18, 0, Math.PI * 2);
        ctx.stroke();
      } else if (holdProgressRef.current > 0 && displayDistance <= TAP_THRESHOLD_PX) {
        const radius = 8 + holdProgressRef.current * 14;
        ctx.strokeStyle = "rgba(250, 204, 21, 0.95)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(startX, startY, radius, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = "rgba(250, 204, 21, 0.25)";
        ctx.beginPath();
        ctx.arc(startX, startY, 6, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillStyle = "rgba(59, 130, 246, 0.35)";
        ctx.beginPath();
        ctx.arc(startX, startY, 6, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, []);

  const paintCanvas = useCallback(
    (dragTo?: { x: number; y: number } | null) => {
      const frame = latestFrameRef.current;
      if (!frame?.image || !frame.width || !frame.height) {
        return;
      }

      if (frameImageRef.current && frameImageSrcRef.current === frame.image) {
        renderToCanvas(dragTo);
        return;
      }

      const image = new Image();
      image.onload = () => {
        frameImageRef.current = image;
        frameImageSrcRef.current = frame.image ?? null;
        renderToCanvas(dragTo);
      };
      image.src = frame.image;
    },
    [renderToCanvas]
  );

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const updateSize = () => {
      const width = Math.floor(viewport.clientWidth);
      const height = Math.floor(viewport.clientHeight);
      if (width <= 0 || height <= 0) {
        return;
      }
      viewportSizeRef.current = { width, height };
      setViewportSize({ width, height });
      paintCanvas();
    };

    updateSize();

    const observer = new ResizeObserver(updateSize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [paintCanvas]);

  useEffect(() => {
    paintCanvas();
  }, [viewportSize, paintCanvas]);

  useEffect(() => {
    if (!selectedSerial) {
      setConnected(false);
      latestFrameRef.current = null;
      frameImageRef.current = null;
      frameImageSrcRef.current = null;
      paintCanvas();
      return;
    }

    const socket = createScreenStream(selectedSerial, 5);

    socket.onopen = () => {
      setConnected(true);
      setError(null);
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as ScreenFrame;
      if (data.type === "error") {
        setError(data.message ?? "设备连接异常");
        return;
      }
      if (data.image && data.width && data.height) {
        latestFrameRef.current = data;
        paintCanvas();
      }
    };

    socket.onerror = () => {
      setConnected(false);
      setError("屏幕流连接失败");
    };

    socket.onclose = () => {
      setConnected(false);
    };

    return () => socket.close();
  }, [selectedSerial, paintCanvas]);

  const toDeviceCoords = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const rect = canvas?.getBoundingClientRect();
    const display = displayRectRef.current;
    const device = deviceSizeRef.current;

    if (!rect || !device.width || !display.width) {
      return null;
    }

    const x = clientX - rect.left;
    const y = clientY - rect.top;

    if (
      x < display.offsetX ||
      y < display.offsetY ||
      x > display.offsetX + display.width ||
      y > display.offsetY + display.height
    ) {
      return null;
    }

    const relativeX = (x - display.offsetX) / display.width;
    const relativeY = (y - display.offsetY) / display.height;

    return {
      x: Math.round(relativeX * device.width),
      y: Math.round(relativeY * device.height),
    };
  }, []);

  const startHoldAnimation = useCallback(() => {
    const startedAt = pointerRef.current?.startedAt ?? Date.now();

    const tick = () => {
      if (!pointerRef.current) {
        holdProgressRef.current = 0;
        return;
      }

      const elapsed = Date.now() - startedAt;
      holdProgressRef.current = Math.min(elapsed / LONG_PRESS_TRIGGER_MS, 1);
      paintCanvas();

      if (holdProgressRef.current < 1) {
        holdAnimFrameRef.current = window.requestAnimationFrame(tick);
      }
    };

    holdAnimFrameRef.current = window.requestAnimationFrame(tick);
  }, [paintCanvas]);

  const triggerLongPress = useCallback(async () => {
    const start = pointerRef.current;
    const serial = selectedSerialRef.current;
    if (!start || !serial || longPressTriggeredRef.current) {
      return;
    }

    const current = dragCurrentRef.current;
    if (!current) {
      return;
    }

    const displayDistance = Math.hypot(current.x - start.clientX, current.y - start.clientY);
    if (displayDistance > TAP_THRESHOLD_PX) {
      return;
    }

    longPressTriggeredRef.current = true;
    holdProgressRef.current = 1;
    paintCanvas();

    try {
      await api.longPress(start.deviceX, start.deviceY, LONG_PRESS_DURATION_MS, serial);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "长按失败");
    }
  }, [paintCanvas]);

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const coords = toDeviceCoords(event.clientX, event.clientY);
    if (!coords) {
      return;
    }

    resetPointerState();

    pointerRef.current = {
      clientX: event.clientX,
      clientY: event.clientY,
      deviceX: coords.x,
      deviceY: coords.y,
      startedAt: Date.now(),
    };
    dragCurrentRef.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
    startHoldAnimation();

    longPressTimerRef.current = window.setTimeout(() => {
      void triggerLongPress();
    }, LONG_PRESS_TRIGGER_MS);

    paintCanvas({ x: event.clientX, y: event.clientY });
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!pointerRef.current) {
      return;
    }

    dragCurrentRef.current = { x: event.clientX, y: event.clientY };
    const displayDistance = Math.hypot(
      event.clientX - pointerRef.current.clientX,
      event.clientY - pointerRef.current.clientY
    );

    if (displayDistance > TAP_THRESHOLD_PX && !longPressTriggeredRef.current) {
      clearLongPressTimer();
    }

    paintCanvas({ x: event.clientX, y: event.clientY });
  };

  const handlePointerUp = async (event: React.PointerEvent<HTMLCanvasElement>) => {
    const start = pointerRef.current;
    const wasLongPress = longPressTriggeredRef.current;
    clearLongPressTimer();
    pointerRef.current = null;
    dragCurrentRef.current = null;
    longPressTriggeredRef.current = false;
    holdProgressRef.current = 0;
    paintCanvas();

    if (!start || !selectedSerial || wasLongPress) {
      return;
    }

    const end = toDeviceCoords(event.clientX, event.clientY);
    if (!end) {
      return;
    }

    const displayDistance = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY);

    try {
      if (displayDistance > TAP_THRESHOLD_PX) {
        await api.swipe(start.deviceX, start.deviceY, end.x, end.y, 300, selectedSerial);
      } else {
        await api.tap(start.deviceX, start.deviceY, selectedSerial);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  };

  const handlePointerCancel = () => {
    resetPointerState();
    paintCanvas();
  };

  return (
    <section className="panel device-panel">
      <header className="panel-header device-header">
        <div className="device-header-title">
          <h2>设备屏幕</h2>
          <span className="panel-hint">
            {connected
              ? "单击=点击，按住=长按，拖拽=滑动"
              : "请连接 Android 设备并开启 USB 调试"}
          </span>
        </div>

        <AppPermissionControls
          devices={devices}
          serial={selectedSerial}
          onSelectDevice={onSelectDevice}
          onMessage={setPermissionMessage}
          onPermissionPresetAdded={onPermissionPresetAdded}
        />
        {permissionMessage && <div className="permission-message">{permissionMessage}</div>}
      </header>

      <div className="panel-body device-body">
        <div className="device-viewport" ref={viewportRef}>
          {error && <div className="device-error">{error}</div>}
          <canvas
            ref={canvasRef}
            className="device-canvas"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerCancel}
          />
          {!selectedSerial && (
            <div className="device-placeholder">
              <p>未检测到设备</p>
              <p>请通过 USB 连接手机并运行 adb devices 确认</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
