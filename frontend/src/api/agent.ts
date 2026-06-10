import { api } from "./client";
import { readApiResponse } from "./http";
import type {
  AgentLogItem,
  AgentRunState,
  CaseListItem,
  DeviceReplayStreamEvent,
  ProvidersResponse,
  StreamEvent,
} from "../types/agent";

function toCaseListItem(
  item: Awaited<ReturnType<typeof api.listCases>>[number]
): CaseListItem {
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

const API_BASE = "/api/agent-test";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const agentApi = {
  checkReady: async () => {
    const response = await fetch(`${API_BASE}/cases?limit=1`);
    return response.ok;
  },

  listCases: async (limit = 10): Promise<CaseListItem[]> => {
    const cases = await api.listCases();
    return cases
      .sort((a, b) => {
        const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0;
        const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0;
        return bTime - aTime;
      })
      .slice(0, limit)
      .map(toCaseListItem);
  },

  listProviders: () => request<ProvidersResponse>("/providers"),

  startRun: (
    caseId: number,
    llmProvider?: string | null,
    options?: { enableVerifier?: boolean }
  ) =>
    request<AgentRunState>("/runs", {
      method: "POST",
      body: JSON.stringify({
        case_id: caseId,
        auto_run: false,
        enable_verifier: options?.enableVerifier ?? false,
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),

  getRun: (runId: string) => request<AgentRunState>(`/runs/${runId}`),

  getLogs: (runId: string, agentType?: string) => {
    const query = agentType ? `?agent_type=${encodeURIComponent(agentType)}` : "";
    return request<{ run_id: string; logs: AgentLogItem[] }>(`/runs/${runId}/logs${query}`);
  },

  cancelRun: (runId: string) => request<void>(`/runs/${runId}`, { method: "DELETE" }),

  streamRun: (
    runId: string,
    handlers: {
      onEvent: (event: StreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    }
  ) => {
    const source = new EventSource(`${API_BASE}/runs/${runId}/stream`);

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as StreamEvent;
        handlers.onEvent(event);
        if (event.type === "done") {
          source.close();
          handlers.onDone?.();
        }
      } catch (error) {
        handlers.onError?.(error instanceof Error ? error : new Error("流式数据解析失败"));
      }
    };

    source.onerror = () => {
      source.close();
      handlers.onError?.(new Error("Agent 执行流连接中断，请确认后端已重启"));
      handlers.onDone?.();
    };

    return () => source.close();
  },

  streamDeviceReplay: (
    runId: string,
    handlers: {
      onEvent: (event: DeviceReplayStreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    },
    stepIntervalMs = 3000
  ) => {
    const query = `?step_interval_ms=${encodeURIComponent(String(stepIntervalMs))}`;
    const source = new EventSource(`${API_BASE}/runs/${runId}/device-replay/stream${query}`);

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as DeviceReplayStreamEvent;
        handlers.onEvent(event);
        if (event.type === "done" || event.type === "error") {
          source.close();
          handlers.onDone?.();
        }
      } catch (error) {
        handlers.onError?.(error instanceof Error ? error : new Error("真机回放数据解析失败"));
      }
    };

    source.onerror = () => {
      source.close();
      handlers.onError?.(new Error("真机回放连接中断，请确认设备已连接且后端正常"));
      handlers.onDone?.();
    };

    return () => source.close();
  },
};
