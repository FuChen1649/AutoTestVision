import type { ActionIntent, AgentStepRecord, StepAttemptRecord } from "../types/agent";

export interface ReplayFrame {
  stepOrder: number;
  label: string;
  description: string;
  imageSrc: string;
  intent: ActionIntent | null;
}

export function buildReplayFrames(
  attempts: StepAttemptRecord[],
  steps: AgentStepRecord[]
): ReplayFrame[] {
  const stepByOrder = new Map(steps.map((step) => [step.step_order, step]));
  const successStepOrders = steps
    .filter((step) => step.status === "success")
    .map((step) => step.step_order)
    .sort((a, b) => a - b);

  const frames: ReplayFrame[] = [];

  for (const stepOrder of successStepOrders) {
    const stepAttempts = attempts
      .filter((attempt) => attempt.step_order === stepOrder)
      .sort((a, b) => a.attempt_index - b.attempt_index);

    const successAttempt = [...stepAttempts].reverse().find((attempt) => attempt.status === "success");
    if (!successAttempt) {
      continue;
    }

    const imageSrc = successAttempt.before_image_annotated || successAttempt.before_image;
    if (!imageSrc) {
      continue;
    }

    const step = stepByOrder.get(stepOrder);
    frames.push({
      stepOrder,
      label: `step${stepOrder + 1}`,
      description: step?.description ?? `步骤 ${stepOrder + 1}`,
      imageSrc,
      intent: successAttempt.intent ?? step?.intent ?? null,
    });
  }

  return frames;
}
