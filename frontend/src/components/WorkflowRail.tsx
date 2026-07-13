import { Link } from "react-router-dom";
import { WORKFLOW_STAGES, type WorkflowStageId } from "../types/workflow";
import "./WorkflowRail.css";

interface Props {
  activeId?: WorkflowStageId | null;
  caseId?: number | null;
  compact?: boolean;
}

function stageHref(id: WorkflowStageId, caseId?: number | null): string {
  if (id === "author") return caseId ? `/cases/${caseId}/edit` : "/cases";
  if (id === "generate") return caseId ? `/agent/generate/${caseId}` : "/agent/execute";
  if (id === "execute") return caseId ? `/agent/execute/${caseId}` : "/agent/execute";
  return "/reports";
}

export default function WorkflowRail({ activeId, caseId, compact }: Props) {
  return (
    <nav className={`wf-rail ${compact ? "wf-rail-compact" : ""}`} aria-label="测试工作流">
      {WORKFLOW_STAGES.map((stage, i) => {
        const active = stage.id === activeId;
        return (
          <div key={stage.id} className="wf-rail-item-wrap">
            {i > 0 && <span className="wf-rail-connector" aria-hidden />}
            <Link
              to={stageHref(stage.id, caseId)}
              className={`wf-rail-item ${active ? "active" : ""}`}
              title={stage.label}
            >
              <span className="wf-rail-index">{stage.index}</span>
              <span className="wf-rail-label">{compact ? stage.short : stage.label}</span>
            </Link>
          </div>
        );
      })}
    </nav>
  );
}
