import { useMemo, useState } from "react";
import ImageLightbox from "./ImageLightbox";
import AgentExecutionReplay from "./AgentExecutionReplay";
import type { AgentStepRecord, StepAttemptRecord } from "../types/agent";
import { buildReplayFrames } from "../utils/buildReplayFrames";

interface AgentExecutionGalleryProps {
  attempts: StepAttemptRecord[];
  steps?: AgentStepRecord[];
}

interface LightboxState {
  src: string;
  alt: string;
  title: string;
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

export default function AgentExecutionGallery({ attempts, steps = [] }: AgentExecutionGalleryProps) {
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const [replayOpen, setReplayOpen] = useState(false);

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

  if (sortedAttempts.length === 0) {
    return <div className="agent-panel-empty">执行后将显示截图</div>;
  }

  return (
    <>
      <div className="agent-gallery-toolbar">
        <button
          type="button"
          className="agent-gallery-replay-btn"
          disabled={replayFrames.length === 0}
          title={
            replayFrames.length === 0
              ? "暂无成功步骤的执行前截图，无法回放"
              : `按成功步骤顺序回放 ${replayFrames.length} 张标注截图`
          }
          onClick={() => setReplayOpen(true)}
        >
          回放
        </button>
        {replayFrames.length > 0 && (
          <span className="agent-gallery-replay-hint">{replayFrames.length} 步可回放</span>
        )}
      </div>
      <div className="agent-execution-gallery">
        {sortedAttempts.map((attempt) => {
          const label = attemptLabel(attempt);
          const beforeSrc = attempt.before_image_annotated || attempt.before_image;
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
    </>
  );
}
