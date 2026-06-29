import { readApiResponse } from "./http";
import type { CaseData } from "../types";
import type { AgentRunState } from "../types/agent";
import type { CodeRunState } from "../types/agentCode";

export type CaseAgentExecMode = "position" | "code";

export interface LiveStepExecuteRequest {
  case_id?: number;
  case_name: string;
  script_content: string;
  steps: CaseData["steps"];
  commit_step_index: number;
  agent_mode: CaseAgentExecMode;
  run_id?: string;
  serial?: string | null;
  llm_provider?: string | null;
  enable_verifier?: boolean;
}

export interface LiveStepExecuteResponse {
  case: CaseData;
  run_id: string;
  agent_mode: CaseAgentExecMode;
  run: AgentRunState | CodeRunState;
  finished: boolean;
  message: string;
}

const API_BASE = "/api/cases/live";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const caseLiveApi = {
  executeStep: (payload: LiveStepExecuteRequest) =>
    request<LiveStepExecuteResponse>("/execute-step", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        serial: payload.serial ?? undefined,
        llm_provider: payload.llm_provider ?? undefined,
      }),
    }),
};
