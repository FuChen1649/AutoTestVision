import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ActionIntent } from "../types/agent";
import type { ReplayFrame } from "../utils/buildReplayFrames";
import "./AgentExecutionReplay.css";

interface AgentExecutionReplayProps {
  frames: ReplayFrame[];
  onClose: () => void;
}

interface ImageLayout {
  offsetX: number;
  offsetY: number;
  scale: number;
  displayWidth: number;
  displayHeight: number;
}

interface HotspotRect {
  left: number;
  top: number;
  width: number;
  height: number;
  shape: "circle" | "rect";
  label: string;
}

function intentHotspot(intent: ActionIntent | null, layout: ImageLayout): HotspotRect | null {
  if (!intent || intent.action === "skip") {
    return null;
  }

  const { offsetX, offsetY, scale } = layout;

  if (
    (intent.action === "tap" || intent.action === "long_press") &&
    intent.x != null &&
    intent.y != null
  ) {
    const radius = (intent.action === "long_press" ? 28 : 18) + 12;
    const size = radius * 2 * scale;
    return {
      left: offsetX + intent.x * scale - radius * scale,
      top: offsetY + intent.y * scale - radius * scale,
      width: size,
      height: size,
      shape: "circle",
      label: intent.action === "long_press" ? "长按" : "点击",
    };
  }

  if (
    intent.action === "swipe" &&
    intent.x != null &&
    intent.y != null &&
    intent.x2 != null &&
    intent.y2 != null
  ) {
    const x1 = offsetX + intent.x * scale;
    const y1 = offsetY + intent.y * scale;
    const x2 = offsetX + intent.x2 * scale;
    const y2 = offsetY + intent.y2 * scale;
    const pad = 16;
    const left = Math.min(x1, x2) - pad;
    const top = Math.min(y1, y2) - pad;
    return {
      left,
      top,
      width: Math.abs(x2 - x1) + pad * 2,
      height: Math.abs(y2 - y1) + pad * 2,
      shape: "rect",
      label: "滑动",
    };
  }

  return null;
}

function measureImageLayout(
  stage: HTMLDivElement | null,
  image: HTMLImageElement | null
): ImageLayout | null {
  if (!stage || !image || !image.naturalWidth || !image.naturalHeight) {
    return null;
  }

  const stageWidth = stage.clientWidth;
  const stageHeight = stage.clientHeight;
  const scale = Math.min(stageWidth / image.naturalWidth, stageHeight / image.naturalHeight);
  const displayWidth = image.naturalWidth * scale;
  const displayHeight = image.naturalHeight * scale;

  return {
    offsetX: (stageWidth - displayWidth) / 2,
    offsetY: (stageHeight - displayHeight) / 2,
    scale,
    displayWidth,
    displayHeight,
  };
}

export default function AgentExecutionReplay({ frames, onClose }: AgentExecutionReplayProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [layout, setLayout] = useState<ImageLayout | null>(null);
  const [finished, setFinished] = useState(false);

  const currentFrame = frames[frameIndex];
  const isLastFrame = frameIndex >= frames.length - 1;

  const updateLayout = useCallback(() => {
    setLayout(measureImageLayout(stageRef.current, imageRef.current));
  }, []);

  useLayoutEffect(() => {
    updateLayout();
  }, [frameIndex, currentFrame?.imageSrc, updateLayout]);

  useEffect(() => {
    const onResize = () => updateLayout();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [updateLayout]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  const advance = () => {
    if (finished) {
      onClose();
      return;
    }
    if (isLastFrame) {
      setFinished(true);
      return;
    }
    setFrameIndex((index) => index + 1);
  };

  const hotspot = layout && currentFrame ? intentHotspot(currentFrame.intent, layout) : null;

  return (
    <div className="agent-replay-overlay" role="dialog" aria-modal="true" aria-label="用例回放">
      <div className="agent-replay-dialog">
        <header className="agent-replay-header">
          <div className="agent-replay-header-main">
            <strong>回放</strong>
            <span>
              {finished
                ? "已完成全部步骤"
                : `步骤 ${frameIndex + 1}/${frames.length} · ${currentFrame?.label ?? ""}`}
            </span>
          </div>
          <button type="button" className="agent-replay-close" onClick={onClose}>
            关闭
          </button>
        </header>

        <p className="agent-replay-description">{currentFrame?.description}</p>

        <div className="agent-replay-stage" ref={stageRef}>
          {currentFrame && (
            <img
              ref={imageRef}
              className="agent-replay-image"
              src={currentFrame.imageSrc}
              alt={`${currentFrame.label} 执行前`}
              onLoad={updateLayout}
            />
          )}

          {hotspot && !finished && (
            <button
              type="button"
              className={
                hotspot.shape === "circle"
                  ? "agent-replay-hotspot agent-replay-hotspot-circle"
                  : "agent-replay-hotspot agent-replay-hotspot-rect"
              }
              style={{
                left: hotspot.left,
                top: hotspot.top,
                width: hotspot.width,
                height: hotspot.height,
              }}
              onClick={advance}
              title={`${hotspot.label} · ${isLastFrame ? "完成回放" : "下一步"}`}
              aria-label={`${hotspot.label}，${isLastFrame ? "完成回放" : "进入下一步"}`}
            >
              <span className="agent-replay-hotspot-pulse" />
            </button>
          )}

          {!hotspot && !finished && (
            <button type="button" className="agent-replay-continue" onClick={advance}>
              {isLastFrame ? "完成回放" : "下一步"}
            </button>
          )}

          {finished && (
            <div className="agent-replay-complete">
              <p>用例操作过程已回放完成</p>
              <button type="button" className="agent-replay-complete-btn" onClick={onClose}>
                关闭
              </button>
            </div>
          )}
        </div>

        <footer className="agent-replay-footer">
          {finished ? (
            <span>点击关闭按钮退出回放</span>
          ) : hotspot ? (
            <span>点击屏幕上的标注区域，进入下一步操作</span>
          ) : (
            <span>本步骤无点击标注，请使用「下一步」继续</span>
          )}
          <div className="agent-replay-dots">
            {frames.map((frame, index) => (
              <span
                key={frame.stepOrder}
                className={
                  index === frameIndex
                    ? "agent-replay-dot agent-replay-dot-active"
                    : index < frameIndex || finished
                      ? "agent-replay-dot agent-replay-dot-done"
                      : "agent-replay-dot"
                }
              />
            ))}
          </div>
        </footer>
      </div>
    </div>
  );
}
