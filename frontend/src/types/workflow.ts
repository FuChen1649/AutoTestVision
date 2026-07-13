import type { NavGroup, NavItem } from "./navigation";

/** 主工作流阶段 — 用于顶栏与 Case 卡片 */
export type WorkflowStageId = "author" | "generate" | "execute" | "report";

export interface WorkflowStage {
  id: WorkflowStageId;
  index: number;
  label: string;
  short: string;
  path: string;
  matchPrefix: string;
}

export const WORKFLOW_STAGES: WorkflowStage[] = [
  { id: "author", index: 1, label: "编写 Case", short: "编写", path: "/cases", matchPrefix: "/cases" },
  {
    id: "generate",
    index: 2,
    label: "双脚本生成",
    short: "生成",
    path: "/agent/generate",
    matchPrefix: "/agent/generate",
  },
  {
    id: "execute",
    index: 3,
    label: "执行验证",
    short: "执行",
    path: "/agent/execute",
    matchPrefix: "/agent/execute",
  },
  { id: "report", index: 4, label: "报告复盘", short: "报告", path: "/reports", matchPrefix: "/reports" },
];

export function resolveWorkflowStage(pathname: string): WorkflowStage | null {
  // Dual 生成页归入「执行」阶段（工作台第三类路径）
  if (pathname.startsWith("/agent/generate") || pathname.startsWith("/agent/execute")) {
    return WORKFLOW_STAGES[2];
  }
  if (pathname === "/reports" || pathname.startsWith("/reports")) return WORKFLOW_STAGES[3];
  if (pathname === "/cases" || pathname.startsWith("/cases/")) return WORKFLOW_STAGES[0];
  return null;
}

export function caseStageStatus(
  scriptStatus: string | null | undefined,
  lastRunStatus: string | null | undefined
): Record<WorkflowStageId, "done" | "active" | "todo" | "failed"> {
  const scriptReady = scriptStatus === "ready" || scriptStatus === "completed";
  const scriptFailed = scriptStatus === "failed";
  const scriptRunning = scriptStatus === "generating" || scriptStatus === "running";
  const runDone = lastRunStatus === "completed" || lastRunStatus === "success";
  const runFailed = lastRunStatus === "failed";
  const runActive = lastRunStatus === "running";

  return {
    author: "done",
    generate: scriptFailed
      ? "failed"
      : scriptReady
        ? "done"
        : scriptRunning
          ? "active"
          : "todo",
    execute: runFailed
      ? "failed"
      : runDone
        ? "done"
        : runActive
          ? "active"
          : scriptReady
            ? "todo"
            : "todo",
    report: runDone || runFailed ? "done" : "todo",
  };
}

export const NAV_ICONS: Record<string, string> = {
  "/cases": "◇",
  "/tasks": "◎",
  "/agent/execute": "▷",
  "/batch": "☰",
  "/reports": "▣",
  "/logs": "≡",
  "/devices": "▣",
  "/resources": "▦",
  "/monkey": "※",
  "/data/cleaning": "◎",
  "/data/flywheel": "↻",
};

export function navIcon(item: NavItem): string {
  return NAV_ICONS[item.path] ?? "·";
}

export type { NavGroup, NavItem };
