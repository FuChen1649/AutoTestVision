import type { AgentLogItem, AgentRunState, AgentStepRecord } from "../types/agent";

function stepIntentLog(step: AgentStepRecord, baseId: number): AgentLogItem | null {
  if (!step.intent) {
    return null;
  }
  const action = step.intent.action;
  const coord =
    action === "tap" || action === "long_press"
      ? ` (${step.intent.x ?? "?"}, ${step.intent.y ?? "?"})`
      : "";
  return {
    id: baseId,
    step_order: step.step_order,
    agent_type: "intent",
    message: `步骤 ${step.step_order + 1} 执行：${action}${coord}`,
    detail: step.intent as unknown as Record<string, unknown>,
    created_at: new Date().toISOString(),
  };
}

function stepVerifierLog(step: AgentStepRecord, baseId: number): AgentLogItem | null {
  if (!step.verification) {
    return null;
  }
  return {
    id: baseId,
    step_order: step.step_order,
    agent_type: "verifier",
    message: step.verification.success ? "验证通过（跳过或未启用）" : `验证失败：${step.verification.reasoning ?? ""}`,
    detail: step.verification as unknown as Record<string, unknown>,
    created_at: new Date().toISOString(),
  };
}

/** 从 run.steps 合成展示用日志（API 日志缺失或 StrictMode 竞态时的兜底） */
export function buildLogsFromRun(run: AgentRunState): {
  intent: AgentLogItem[];
  verifier: AgentLogItem[];
} {
  const intent: AgentLogItem[] = [];
  const verifier: AgentLogItem[] = [];
  for (const step of run.steps) {
    const intentItem = stepIntentLog(step, 10_000 + step.step_order * 2);
    if (intentItem) {
      intent.push(intentItem);
    }
    const verifierItem = stepVerifierLog(step, 10_000 + step.step_order * 2 + 1);
    if (verifierItem) {
      verifier.push(verifierItem);
    }
  }
  return { intent, verifier };
}

export function isExecutionLog(item: AgentLogItem): boolean {
  return item.agent_type === "intent" || item.agent_type === "executor" || item.agent_type === "system";
}

export function splitExecutionLogs(logs: AgentLogItem[]): {
  intent: AgentLogItem[];
  verifier: AgentLogItem[];
} {
  return {
    intent: logs.filter((item) => isExecutionLog(item)),
    verifier: logs.filter((item) => item.agent_type === "verifier"),
  };
}

export function mergeRunLogs(
  apiLogs: AgentLogItem[],
  run: AgentRunState | null | undefined
): { intent: AgentLogItem[]; verifier: AgentLogItem[] } {
  const fromApi = splitExecutionLogs(apiLogs);
  if (fromApi.intent.length > 0) {
    return fromApi;
  }
  if (run) {
    return buildLogsFromRun(run);
  }
  return { intent: [], verifier: fromApi.verifier };
}
