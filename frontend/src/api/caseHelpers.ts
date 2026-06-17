import type { CaseData } from "../types";
import type { CaseListItem } from "../types/agent";

export function toCaseListItem(item: CaseData): CaseListItem {
  const steps = [...(item.steps ?? [])]
    .sort((a, b) => a.step_order - b.step_order)
    .map((step) => ({
      step_order: step.step_order,
      step_type: step.step_type,
      description: step.description,
    }));
  return {
    id: item.id!,
    name: item.name,
    step_count: steps.length,
    updated_at: item.updated_at ?? new Date().toISOString(),
    steps,
  };
}

export function sortCasesByUpdatedAt(items: CaseListItem[]): CaseListItem[] {
  return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}
