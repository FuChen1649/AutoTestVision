import { useEffect, useMemo, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import ImageLightbox from "./ImageLightbox";
import AgentExecutionReplay from "./AgentExecutionReplay";
import AgentDeviceReplayOverlay from "./AgentDeviceReplayOverlay";
import type { AgentStepRecord, DeviceReplayStreamEvent, StepAttemptRecord } from "../types/agent";
import { buildDeviceReplaySteps } from "../utils/buildDeviceReplaySteps";
import { buildReplayFrames } from "../utils/buildReplayFrames";

interface AgentExecutionGalleryProps {
  attempts: StepAttemptRecord[];
  steps?: AgentStepRecord[];
  runId?: string | null;
  runStatus?: string;
  agentRunning?: boolean;
}

interface LightboxState {
  src: string;
  alt: string;
  title: string;
}

type DeviceReplayPhase = "recover" | "wait" | "step" | "done" | "error";

interface DeviceReplayUiState {
  phase: DeviceReplayPhase;
  message: string;
  detail: string | null;
  stepIndex: number | null;
  totalSteps: number | null;
}

function attemptLabel(attempt: StepAttemptRecord) {
  return `step${attempt.step_order + 1}-${attempt.attempt_index}`;
}

function statusLabel(status: string) {
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  if (status === "running") return "执行中";
  return status;
}

function actionHint(attempt: StepAttemptRecord): string | null {
  if (attempt.status !== "success" || !attempt.intent) {
    return null;
  }
  const intent = attempt.intent;
  if (intent.action === "skip") {
    return attempt.step_type === "permission_preset" ? "权限工具" : "无设备操作";
  }
  if (intent.action === "tap") {
    return `点击 (${intent.x ?? "?"}, ${intent.y ?? "?"})`;
  }
  if (intent.action === "long_press") {
    return `长按 (${intent.x ?? "?"}, ${intent.y ?? "?"})`;
  }
  if (intent.action === "swipe") {
    return `滑动 (${intent.x ?? "?"}, ${intent.y ?? "?"}) → (${intent.x2 ?? "?"}, ${intent.y2 ?? "?"})`;
  }
  return intent.action;
}

function mapDeviceReplayEvent(event: DeviceReplayStreamEvent): Partial<DeviceReplayUiState> {
  if (event.type === "recover") {
    return { phase: "recover", message: event.message || "场景恢复中…", detail: null };
  }
  if (event.type === "wait") {
    return { phase: "wait", message: event.message || "等待中…", detail: null };
  }
  if (event.type === "step") {
    return {
      phase: "step",
      message: event.message || "正在设备上执行…",
      detail: event.action || null,
      stepIndex: event.step_index ?? null,
      totalSteps: event.total_steps ?? null,
    };
  }
  if (event.type === "done") {
    return {
      phase: "done",
      message: event.message || "真机回放完成",
      detail: null,
      totalSteps: event.total_steps ?? null,
    };
  }
  if (event.type === "error") {
    return {
      phase: "error",
      message: event.message || "真机回放失败",
      detail: event.action || null,
      stepIndex: event.step_index ?? null,
      totalSteps: event.total_steps ?? null,
    };
  }
  if (event.type === "start") {
    return {
      phase: "recover",
      message: event.message || "准备真机回放…",
      detail: null,
      totalSteps: event.total_steps ?? null,
    };
  }
  return {};
}

export default function AgentExecutionGallery({
  attempts,
  steps = [],
  runId = null,
  runStatus = "",
  agentRunning = false,
}: AgentExecutionGalleryProps) {
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const [replayOpen, setReplayOpen] = useState(false);
  const [deviceReplayOpen, setDeviceReplayOpen] = useState(false);
  const [deviceReplayUi, setDeviceReplayUi] = useState<DeviceReplayUiState>({
    phase: "recover",
    message: "准备真机回放…",
    detail: null,
    stepIndex: null,
    totalSteps: null,
  });
  const stopDeviceReplayRef = useRef<(() => void) | null>(null);

  const sortedAttempts = useMemo(
    () =>
      [...attempts].sort((a, b) => {
        if (a.step_order !== b.step_order) {
          return a.step_order - b.step_order;
        }
        return a.attempt_index - b.attempt_index;
      }),
    [attempts]
  );

  const replayFrames = useMemo(
    () => buildReplayFrames(sortedAttempts, steps),
    [sortedAttempts, steps]
  );

  const deviceReplaySteps = useMemo(() => buildDeviceReplaySteps(steps), [steps]);

  const canDeviceReplay =
    Boolean(runId) &&
    runStatus !== "running" &&
    !agentRunning &&
    deviceReplaySteps.length > 0 &&
    !deviceReplayOpen;

  useEffect(() => {
    return () => stopDeviceReplayRef.current?.();
  }, []);

  const handleDeviceReplay = () => {
    if (!runId || !canDeviceReplay) {
      return;
    }

    stopDeviceReplayRef.current?.();
    setDeviceReplayOpen(true);
    setDeviceReplayUi({
      phase: "recover",
      message: "准备真机回放…",
      detail: null,
      stepIndex: null,
      totalSteps: deviceReplaySteps.length,
    });

    stopDeviceReplayRef.current = agentApi.streamDeviceReplay(
      runId,
      {
        onEvent: (event) => {
          setDeviceReplayUi((prev) => ({
            ...prev,
            ...mapDeviceReplayEvent(event),
          }));
        },
        onError: (error) => {
          setDeviceReplayUi({
            phase: "error",
            message: error.message,
            detail: null,
            stepIndex: null,
            totalSteps: deviceReplaySteps.length,
          });
        },
        onDone: () => {
          stopDeviceReplayRef.current = null;
        },
      },
      3000
    );
  };

  const closeDeviceReplay = () => {
    stopDeviceReplayRef.current?.();
    stopDeviceReplayRef.current = null;
    setDeviceReplayOpen(false);
  };

  if (sortedAttempts.length === 0) {
    return <div className="agent-panel-empty">执行后将显示截图</div>;
  }

  return (
    <>
      <div className="agent-gallery-toolbar">
        <div className="agent-gallery-toolbar-actions">
          <button
            type="button"
            className="agent-gallery-replay-btn"
            disabled={replayFrames.length === 0}
            title={
              replayFrames.length === 0
                ? "暂无成功步骤的执行前截图，无法虚拟回放"
                : `按成功步骤顺序虚拟回放 ${replayFrames.length} 张标注截图`
            }
            onClick={() => setReplayOpen(true)}
          >
            虚拟回放
          </button>
          <button
            type="button"
            className="agent-gallery-device-replay-btn"
            disabled={!canDeviceReplay}
            title={
              !runId
                ? "请先执行一次 Case"
                : runStatus === "running" || agentRunning
                  ? "Agent 执行中，请结束后再试"
                  : deviceReplaySteps.length === 0
                    ? "暂无成功步骤，无法真机回放"
                    : `在连接设备上重放 ${deviceReplaySteps.length} 个成功步骤（先场景恢复，步间间隔 3 秒）`
            }
            onClick={handleDeviceReplay}
          >
            真机回放
          </button>
        </div>
        {(replayFrames.length > 0 || deviceReplaySteps.length > 0) && (
          <span className="agent-gallery-replay-hint">
            {replayFrames.length > 0 && `${replayFrames.length} 步可虚拟回放`}
            {replayFrames.length > 0 && deviceReplaySteps.length > 0 && " · "}
            {deviceReplaySteps.length > 0 && `${deviceReplaySteps.length} 步可真机回放`}
          </span>
        )}
      </div>
      <div className="agent-execution-gallery">
        {sortedAttempts.map((attempt) => {
          const label = attemptLabel(attempt);
          const beforeSrc = attempt.before_image_annotated || attempt.before_image;
          const hint = actionHint(attempt);
          const key = `${attempt.step_order}-${attempt.attempt_index}`;
          return (
            <article
              key={key}
              className={`agent-attempt-card agent-attempt-${attempt.status}`}
            >
              <header className="agent-attempt-header">
                <strong>{label}</strong>
                <span className={`agent-attempt-status agent-attempt-status-${attempt.status}`}>
                  {statusLabel(attempt.status)}
                </span>
              </header>
              {hint && <p className="agent-attempt-action-hint">操作：{hint}</p>}
              <div className="agent-attempt-pair">
                <figure className="agent-attempt-shot">
                  <figcaption>执行前</figcaption>
                  {beforeSrc ? (
                    <button
                      type="button"
                      className="agent-attempt-image-btn"
                      onClick={() =>
                        setLightbox({
                          src: beforeSrc,
                          alt: `${label} 执行前`,
                          title: `${label} · 执行前`,
                        })
                      }
                    >
                      <img src={beforeSrc} alt={`${label} 执行前`} />
                    </button>
                  ) : (
                    <div className="agent-image-placeholder">暂无</div>
                  )}
                </figure>
                <figure className="agent-attempt-shot">
                  <figcaption>执行后</figcaption>
                  {attempt.after_image ? (
                    <button
                      type="button"
                      className="agent-attempt-image-btn"
                      onClick={() =>
                        setLightbox({
                          src: attempt.after_image!,
                          alt: `${label} 执行后`,
                          title: `${label} · 执行后`,
                        })
                      }
                    >
                      <img src={attempt.after_image} alt={`${label} 执行后`} />
                    </button>
                  ) : (
                    <div className="agent-image-placeholder">暂无</div>
                  )}
                </figure>
              </div>
              {attempt.error && attempt.status === "failed" && (
                <p className="agent-attempt-error">{attempt.error}</p>
              )}
            </article>
          );
        })}
      </div>
      {lightbox && (
        <ImageLightbox
          src={lightbox.src}
          alt={lightbox.alt}
          title={lightbox.title}
          onClose={() => setLightbox(null)}
        />
      )}
      {replayOpen && replayFrames.length > 0 && (
        <AgentExecutionReplay frames={replayFrames} onClose={() => setReplayOpen(false)} />
      )}
      {deviceReplayOpen && (
        <AgentDeviceReplayOverlay
          message={deviceReplayUi.message}
          detail={deviceReplayUi.detail}
          stepIndex={deviceReplayUi.stepIndex}
          totalSteps={deviceReplayUi.totalSteps}
          phase={deviceReplayUi.phase}
          onClose={closeDeviceReplay}
        />
      )}
    </>
  );
}
