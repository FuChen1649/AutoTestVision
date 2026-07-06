import { useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import AgentTestPage from "./AgentTestPage";
import AgentTestCodePage from "./AgentTestCodePage";
import "./PlatformPages.css";

export default function AgentExecutePage() {
  const { caseId: caseIdParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const mode = searchParams.get("mode") === "code" ? "code" : "position";
  const caseId = caseIdParam ? Number(caseIdParam) : null;

  const bootstrap = useMemo(() => {
    if (!caseId) return null;
    return { caseId, runId: searchParams.get("runId") ?? "", mode } as const;
  }, [caseId, mode, searchParams]);

  return (
    <div className="platform-page" style={{ padding: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "12px 20px", borderBottom: "1px solid #1f2937" }}>
        <div className="platform-tabs" style={{ marginBottom: 0 }}>
          <button
            type="button"
            className={mode === "position" ? "platform-tab active" : "platform-tab"}
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("mode", "position");
              setSearchParams(next);
            }}
          >
            Position 执行
          </button>
          <button
            type="button"
            className={mode === "code" ? "platform-tab active" : "platform-tab"}
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("mode", "code");
              setSearchParams(next);
            }}
          >
            Code 执行
          </button>
        </div>
        {caseId && (
          <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "#9ca3af" }}>
            Case #{caseId} · 优先使用已生成的预置脚本，无脚本时 fallback 实时 Agent
          </p>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {mode === "position" ? (
          <AgentTestPage
            initialCaseId={caseId}
            bootstrap={bootstrap?.mode === "position" && bootstrap.runId ? { caseId: bootstrap.caseId, runId: bootstrap.runId, mode: "position" } : null}
          />
        ) : (
          <AgentTestCodePage
            initialCaseId={caseId}
            bootstrap={bootstrap?.mode === "code" && bootstrap.runId ? { caseId: bootstrap.caseId, runId: bootstrap.runId, mode: "code" } : null}
          />
        )}
      </div>
    </div>
  );
}
