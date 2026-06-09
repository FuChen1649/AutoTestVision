import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { cropImageDataUrl, normalizeRect, type ImageRect } from "../utils/image";
import type { StepScreenBinding } from "../types";

interface DisplayRect {
  offsetX: number;
  offsetY: number;
  width: number;
  height: number;
}

interface StepScreenCaptureModalProps {
  open: boolean;
  serial: string | null;
  stepIndex: number;
  onClose: () => void;
  onSave: (stepIndex: number, binding: StepScreenBinding) => void;
}

interface PointerPoint {
  x: number;
  y: number;
}

const MIN_SELECTION_PX = 8;

export default function StepScreenCaptureModal({
  open,
  serial,
  stepIndex,
  onClose,
  onSave,
}: StepScreenCaptureModalProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const imageSrcRef = useRef<string | null>(null);
  const deviceSizeRef = useRef({ width: 0, height: 0 });
  const displayRectRef = useRef<DisplayRect>({ offsetX: 0, offsetY: 0, width: 0, height: 0 });
  const pointerStartRef = useRef<PointerPoint | null>(null);
  const selectionRef = useRef<ImageRect | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const paint = useCallback((dragTo?: PointerPoint | null) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const image = imageRef.current;
    const device = deviceSizeRef.current;

    if (!canvas || !container || !image || !device.width) {
      return;
    }

    const viewportWidth = container.clientWidth;
    const viewportHeight = container.clientHeight;
    const scale = Math.min(viewportWidth / device.width, viewportHeight / device.height);
    const displayWidth = Math.floor(device.width * scale);
    const displayHeight = Math.floor(device.height * scale);
    const offsetX = Math.floor((viewportWidth - displayWidth) / 2);
    const offsetY = Math.floor((viewportHeight - displayHeight) / 2);

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewportWidth * dpr);
    canvas.height = Math.floor(viewportHeight * dpr);
    canvas.style.width = `${viewportWidth}px`;
    canvas.style.height = `${viewportHeight}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, viewportWidth, viewportHeight);
    ctx.fillStyle = "#030712";
    ctx.fillRect(0, 0, viewportWidth, viewportHeight);
    ctx.drawImage(image, offsetX, offsetY, displayWidth, displayHeight);

    displayRectRef.current = { offsetX, offsetY, width: displayWidth, height: displayHeight };

    const start = pointerStartRef.current;
    const rect =
      start && dragTo
        ? normalizeRect(start.x, start.y, dragTo.x, dragTo.y)
        : selectionRef.current;

    if (rect && rect.width >= MIN_SELECTION_PX && rect.height >= MIN_SELECTION_PX) {
      ctx.strokeStyle = "rgba(59, 130, 246, 0.95)";
      ctx.lineWidth = 2;
      ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);
      ctx.fillStyle = "rgba(59, 130, 246, 0.15)";
      ctx.fillRect(rect.x, rect.y, rect.width, rect.height);
    }
  }, []);

  const loadScreenshot = useCallback(async () => {
    if (!serial) {
      setError("请先连接设备");
      return;
    }

    setLoading(true);
    setError(null);
    selectionRef.current = null;
    pointerStartRef.current = null;

    try {
      const frame = await api.getScreenshot(serial);
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error("截图加载失败"));
        image.src = frame.image;
      });

      imageRef.current = image;
      imageSrcRef.current = frame.image;
      deviceSizeRef.current = { width: frame.width, height: frame.height };
      paint();
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取设备屏幕失败");
    } finally {
      setLoading(false);
    }
  }, [serial, paint]);

  useEffect(() => {
    if (!open) {
      return;
    }
    void loadScreenshot();
  }, [open, loadScreenshot]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleResize = () => paint();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [open, paint]);

  const toCanvasPoint = (clientX: number, clientY: number): PointerPoint | null => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return null;
    }
    const rect = canvas.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  };

  const toDeviceRect = (displaySelection: ImageRect): ImageRect | null => {
    const display = displayRectRef.current;
    const device = deviceSizeRef.current;
    if (!display.width || !device.width) {
      return null;
    }

    const x = Math.round(((displaySelection.x - display.offsetX) / display.width) * device.width);
    const y = Math.round(((displaySelection.y - display.offsetY) / display.height) * device.height);
    const width = Math.round((displaySelection.width / display.width) * device.width);
    const height = Math.round((displaySelection.height / display.height) * device.height);

    if (width < MIN_SELECTION_PX || height < MIN_SELECTION_PX) {
      return null;
    }

    return {
      x: Math.max(0, Math.min(x, device.width - 1)),
      y: Math.max(0, Math.min(y, device.height - 1)),
      width: Math.max(1, Math.min(width, device.width - x)),
      height: Math.max(1, Math.min(height, device.height - y)),
    };
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const point = toCanvasPoint(event.clientX, event.clientY);
    if (!point) {
      return;
    }
    pointerStartRef.current = point;
    selectionRef.current = null;
    event.currentTarget.setPointerCapture(event.pointerId);
    paint(point);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!pointerStartRef.current) {
      return;
    }
    const point = toCanvasPoint(event.clientX, event.clientY);
    if (!point) {
      return;
    }
    paint(point);
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const start = pointerStartRef.current;
    pointerStartRef.current = null;
    const end = toCanvasPoint(event.clientX, event.clientY);
    if (!start || !end) {
      paint();
      return;
    }

    const displaySelection = normalizeRect(start.x, start.y, end.x, end.y);
    selectionRef.current =
      displaySelection.width >= MIN_SELECTION_PX && displaySelection.height >= MIN_SELECTION_PX
        ? displaySelection
        : null;
    paint();
  };

  const handleSave = async () => {
    const imageSrc = imageSrcRef.current;
    const device = deviceSizeRef.current;
    const selection = selectionRef.current;

    if (!imageSrc || !device.width) {
      setError("没有可保存的截图");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const deviceRect = selection
        ? toDeviceRect(selection)
        : { x: 0, y: 0, width: device.width, height: device.height };

      if (!deviceRect) {
        setError("请先框选区域");
        setSaving(false);
        return;
      }

      const cropped = await cropImageDataUrl(imageSrc, deviceRect);
      onSave(stepIndex, {
        screen_image: cropped,
        screen_width: device.width,
        screen_height: device.height,
        selection_x: deviceRect.x,
        selection_y: deviceRect.y,
        selection_width: deviceRect.width,
        selection_height: deviceRect.height,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return null;
  }

  return (
    <div className="capture-modal-overlay" onClick={onClose}>
      <div className="capture-modal" onClick={(event) => event.stopPropagation()}>
        <header className="capture-modal-header">
          <div>
            <h3>框选设备屏幕区域</h3>
            <p>按住鼠标拖拽框选，保存后将绑定到当前步骤</p>
          </div>
          <button className="icon-btn" type="button" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="capture-modal-body" ref={containerRef}>
          {loading && <div className="capture-modal-status">正在获取设备屏幕...</div>}
          {error && <div className="capture-modal-error">{error}</div>}
          <canvas
            ref={canvasRef}
            className="capture-modal-canvas"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          />
        </div>

        <footer className="capture-modal-footer">
          <button className="secondary-btn" type="button" onClick={() => void loadScreenshot()} disabled={loading}>
            刷新截图
          </button>
          <button className="primary-btn" type="button" onClick={() => void handleSave()} disabled={saving || loading}>
            {saving ? "保存中..." : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
