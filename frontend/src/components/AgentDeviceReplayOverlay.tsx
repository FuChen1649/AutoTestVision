import { useEffect } from "react";
import "./AgentDeviceReplayOverlay.css";

interface AgentDeviceReplayOverlayProps {
  message: string;
  detail?: string | null;
  stepIndex: number | null;
  totalSteps: number | null;
  phase: "recover" | "wait" | "step" | "done" | "error";
  onClose: () => void;
}

export default function AgentDeviceReplayOverlay({
  message,
  detail,
  stepIndex,
  totalSteps,
  phase,
  onClose,
}: AgentDeviceReplayOverlayProps) {
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && (phase === "done" || phase === "error")) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, phase]);

  const progress =
    stepIndex != null && totalSteps != null && totalSteps > 0
      ? Math.min(100, Math.round(((stepIndex + 1) / totalSteps) * 100))
      : phase === "done"
        ? 100
        : 0;

  return (
    <div className="agent-device-replay-overlay" role="dialog" aria-modal="true" aria-label="真机回放">
      <div className="agent-device-replay-dialog">
        <header className="agent-device-replay-header">
          <strong>真机回放</strong>
          {totalSteps != null && totalSteps > 0 && (
            <span>
              {phase === "done"
                ? `已完成 ${totalSteps} 步`
                : stepIndex != null
                  ? `步骤 ${stepIndex + 1}/${totalSteps}`
                  : `共 ${totalSteps} 步`}
            </span>
          )}
        </header>

        <div className={`agent-device-replay-status agent-device-replay-${phase}`}>
          {phase === "recover" && <span className="agent-device-replay-spinner" />}
          {phase === "wait" && <span className="agent-device-replay-spinner agent-device-replay-spinner-slow" />}
          {phase === "step" && <span className="agent-device-replay-pulse-dot" />}
          {phase === "done" && <span className="agent-device-replay-done-icon">✓</span>}
          {phase === "error" && <span className="agent-device-replay-error-icon">!</span>}
        </div>

        <p className="agent-device-replay-message">{message}</p>
        {detail && <p className="agent-device-replay-detail">{detail}</p>}

        <div className="agent-device-replay-progress">
          <div className="agent-device-replay-progress-bar" style={{ width: `${progress}%` }} />
        </div>

        <footer className="agent-device-replay-footer">
          {phase === "done" || phase === "error" ? (
            <button type="button" className="agent-device-replay-close-btn" onClick={onClose}>
              关闭
            </button>
          ) : (
            <span>请勿操作页面，设备正在执行…</span>
          )}
        </footer>
      </div>
    </div>
  );
}
