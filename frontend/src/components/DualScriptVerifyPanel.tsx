import type { DualStepVerifyReview } from "../types/resultVerify";

interface DualScriptVerifyPanelProps {
  reviews: DualStepVerifyReview[];
  verifyingStepOrder?: number | null;
  active?: boolean;
}

function matchLabel(value: boolean) {
  return value ? "一致" : "不一致";
}

export default function DualScriptVerifyPanel({
  reviews,
  verifyingStepOrder = null,
  active = false,
}: DualScriptVerifyPanelProps) {
  if (!active && reviews.length === 0) {
    return null;
  }

  return (
    <section className="dual-verify-panel">
      <header className="dual-verify-panel-header">
        <h4>双脚本一致性验证</h4>
        <span>逐步比对 Position 与 Code 的执行前/后截图</span>
      </header>
      {active && reviews.length === 0 && verifyingStepOrder == null && (
        <div className="result-empty">准备验证…</div>
      )}
      {reviews.length === 0 && !active && <div className="result-empty">尚未验证</div>}
      <ol className="dual-verify-step-list">
        {reviews.map((review) => (
          <li
            key={review.step_order}
            className={
              review.consistent ? "dual-verify-step dual-verify-ok" : "dual-verify-step dual-verify-bad"
            }
          >
            <div className="dual-verify-step-head">
              <strong>步骤 {review.step_order + 1}</strong>
              <span className={review.consistent ? "dual-verify-badge ok" : "dual-verify-badge bad"}>
                {review.consistent ? "两侧一致" : "存在差异"}
              </span>
            </div>
            <p className="dual-verify-purpose">{review.purpose}</p>
            <div className="dual-verify-tags">
              <span>执行前：{matchLabel(review.before_match)}</span>
              <span>执行后：{matchLabel(review.after_match)}</span>
              {review.confidence != null && <span>置信度 {(review.confidence * 100).toFixed(0)}%</span>}
            </div>
            {review.reasoning && <p className="dual-verify-reasoning">{review.reasoning}</p>}
          </li>
        ))}
        {active && verifyingStepOrder != null && (
          <li className="dual-verify-step dual-verify-running">
            <strong>步骤 {verifyingStepOrder + 1}</strong>
            <span>验证中…</span>
          </li>
        )}
      </ol>
    </section>
  );
}
