import { useMemo } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import AgentTestPage from "./AgentTestPage";
import AgentTestCodePage from "./AgentTestCodePage";
import "./PlatformPages.css";
import "./AgentExecutePage.css";

export default function AgentExecutePage() {
  const { caseId: caseIdParam } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const mode = searchParams.get("mode") === "code" ? "code" : "position";
  const caseId = caseIdParam ? Number(caseIdParam) : null;
  const runId = searchParams.get("runId");

  const bootstrap = useMemo(() => {
    if (!caseId) return null;
    return { caseId, runId: runId ?? "", mode } as const;
  }, [caseId, mode, runId]);

  const goDual = () => {
    navigate(caseId ? `/agent/generate/${caseId}` : "/agent/generate");
  };

  return (
    <div className="platform-page platform-page-flush exec-shell">
      <div className="exec-shell-bar">
        <div className="exec-shell-intro">
          <div className="exec-shell-kicker">Stage 03 · Execute</div>
          <div className="exec-shell-title-row">
            <h2>执行工作台</h2>
            {caseId ? (
              <span className="exec-shell-case">Case #{caseId}</span>
            ) : (
              <span className="exec-shell-case muted">未指定 Case</span>
            )}
            {runId && <span className="exec-shell-run">run {runId.slice(0, 8)}…</span>}
          </div>
          <p>
            Dual 并行生成双脚本；Position / Code 分别执行与回放。左侧选 Case，中间看日志，右侧看步骤。
          </p>
          <div className="exec-shell-flow">
            <span>1. 选路径</span>
            <span className="sep">→</span>
            <span>2. Dual 生成 / 单路径执行</span>
            <span className="sep">→</span>
            <span>3. 看日志与回放</span>
            <span className="sep">→</span>
            <span>4. 去报告复盘</span>
          </div>
        </div>
        <div className="exec-shell-actions">
          <div className="exec-path-switch exec-path-switch-3" role="tablist" aria-label="执行路径">
            <button
              type="button"
              role="tab"
              className="exec-path-btn dual"
              onClick={goDual}
              title="进入双脚本并行生成"
            >
              <strong>Dual</strong>
              <span>双脚本生成</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "position"}
              className={`exec-path-btn pos ${mode === "position" ? "active" : ""}`}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.set("mode", "position");
                setSearchParams(next);
              }}
            >
              <strong>Position</strong>
              <span>视觉坐标</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "code"}
              className={`exec-path-btn code ${mode === "code" ? "active" : ""}`}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.set("mode", "code");
                setSearchParams(next);
              }}
            >
              <strong>Code</strong>
              <span>u2 选择器</span>
            </button>
          </div>
          <div className="exec-shell-links">
            <Link className="platform-btn" to="/tasks">
              任务
            </Link>
            <Link className="platform-btn" to="/reports">
              报告 →
            </Link>
            {runId && (
              <Link
                className="platform-btn"
                to={`/logs?run_uuid=${encodeURIComponent(runId)}&source=${mode}`}
              >
                日志
              </Link>
            )}
          </div>
        </div>
      </div>
      <div className="exec-shell-body">
        {mode === "position" ? (
          <AgentTestPage
            initialCaseId={caseId}
            bootstrap={
              bootstrap?.mode === "position" && bootstrap.runId
                ? { caseId: bootstrap.caseId, runId: bootstrap.runId, mode: "position" }
                : null
            }
          />
        ) : (
          <AgentTestCodePage
            initialCaseId={caseId}
            bootstrap={
              bootstrap?.mode === "code" && bootstrap.runId
                ? { caseId: bootstrap.caseId, runId: bootstrap.runId, mode: "code" }
                : null
            }
          />
        )}
      </div>
    </div>
  );
}
