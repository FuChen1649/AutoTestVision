import type { AgentStepRecord } from "../types/agent";

export interface DeviceReplayStep {
  stepOrder: number;
  label: string;
  description: string;
  stepType: string;
  actionLabel: string;
}

export function buildDeviceReplaySteps(steps: AgentStepRecord[]): DeviceReplayStep[] {
  return steps
    .filter((step) => step.status === "success")
    .sort((a, b) => a.step_order - b.step_order)
    .map((step) => ({
      stepOrder: step.step_order,
      label: `step${step.step_order + 1}`,
      description: step.description,
      stepType: step.step_type,
      actionLabel: describeReplayAction(step),
    }));
}

function describeReplayAction(step: AgentStepRecord): string {
  if (step.step_type === "permission_preset") {
    const pkg = step.metadata?.package;
    return pkg ? `权限工具 · ${String(pkg)}` : "权限工具";
  }

  const intent = step.intent;
  if (!intent) {
    return "未知操作";
  }
  if (intent.action === "skip") {
    return "跳过";
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
