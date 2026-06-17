import { sortCasesByUpdatedAt, toCaseListItem } from "./caseHelpers";
import { api } from "./client";
import { readApiResponse } from "./http";
import type {
  AgentLogItem,
  AgentRunState,
  BatchListItem,
  BatchState,
  BatchStreamEvent,
  CaseListItem,
  DeviceReplayStreamEvent,
  ProvidersResponse,
  StreamEvent,
} from "../types/agent";

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

  listCases: async (limit?: number): Promise<CaseListItem[]> => {
    const cases = sortCasesByUpdatedAt((await api.listCases()).map(toCaseListItem));
    return limit ? cases.slice(0, limit) : cases;
  },

  deleteCase: (caseId: number) => api.deleteCase(caseId),

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

  cancelBatch: (batchId: string) =>
    request<BatchState>(`/batches/${batchId}`, { method: "DELETE" }),

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

  startBatch: (llmProvider?: string | null, options?: { enableVerifier?: boolean }) =>
    request<BatchState>("/batches", {
      method: "POST",
      body: JSON.stringify({
        case_ids: [],
        enable_verifier: options?.enableVerifier ?? false,
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),

  listBatches: (limit = 50) =>
    request<BatchListItem[]>(`/batches?limit=${encodeURIComponent(String(limit))}`),

  getBatch: (batchId: string) => request<BatchState>(`/batches/${batchId}`),

  streamBatch: (
    batchId: string,
    handlers: {
      onEvent: (event: BatchStreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    }
  ) => {
    const source = new EventSource(`${API_BASE}/batches/${batchId}/stream`);

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as BatchStreamEvent;
        handlers.onEvent(event);
        if (event.type === "done" || event.type === "error") {
          source.close();
          handlers.onDone?.();
        }
      } catch (error) {
        handlers.onError?.(error instanceof Error ? error : new Error("批量流数据解析失败"));
      }
    };

    source.onerror = () => {
      source.close();
      handlers.onError?.(new Error("批量执行流连接中断，请确认后端已重启"));
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
