import { sortCasesByUpdatedAt, toCaseListItem } from "./caseHelpers";
import { api } from "./client";
import { readApiResponse } from "./http";
import type { CaseListItem, ProvidersResponse } from "../types/agent";
import type { CodeRunState, CodeStreamEvent } from "../types/agentCode";
import type { DeviceReplayStreamEvent } from "../types/agent";

const API_BASE = "/api/agent-test-code";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const agentCodeApi = {
  checkReady: async () => {
    const response = await fetch(`${API_BASE}/cases?limit=1`);
    return response.ok;
  },

  listCases: async (limit = 10): Promise<CaseListItem[]> => {
    const cases = sortCasesByUpdatedAt((await api.listCasesAll()).map(toCaseListItem));
    return limit ? cases.slice(0, limit) : cases;
  },

  deleteCase: (caseId: number) => api.deleteCase(caseId),

  listProviders: () => request<ProvidersResponse>("/providers"),

  startRun: (caseId: number, llmProvider?: string | null, options?: { enableVerifier?: boolean }) =>
    request<CodeRunState>("/runs", {
      method: "POST",
      body: JSON.stringify({
        case_id: caseId,
        auto_run: false,
        enable_verifier: options?.enableVerifier ?? false,
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),

  getRun: (runId: string) => request<CodeRunState>(`/runs/${runId}`),

  cancelRun: (runId: string) => request<CodeRunState>(`/runs/${runId}/cancel`, { method: "POST" }),

  streamRun: (
    runId: string,
    handlers: {
      onEvent: (event: CodeStreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    }
  ) => {
    const controller = new AbortController();
    let closed = false;

    const finish = () => {
      if (closed) return;
      closed = true;
      handlers.onDone?.();
    };

    void (async () => {
      try {
        const response = await fetch(`${API_BASE}/runs/${runId}/stream`, {
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!response.ok) {
          throw new Error(`执行流连接失败 (${response.status})`);
        }
        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("执行流不可读");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        while (!closed) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";
          for (const chunk of chunks) {
            const dataLine = chunk
              .split("\n")
              .map((line) => line.trim())
              .find((line) => line.startsWith("data:"));
            if (!dataLine) continue;
            const payload = dataLine.replace(/^data:\s?/, "");
            const event = JSON.parse(payload) as CodeStreamEvent;
            handlers.onEvent(event);
            if (event.type === "done" || event.type === "error") {
              closed = true;
              reader.cancel().catch(() => undefined);
              break;
            }
          }
        }
        finish();
      } catch (error) {
        if (controller.signal.aborted) {
          finish();
          return;
        }
        handlers.onError?.(error instanceof Error ? error : new Error("执行流连接中断"));
        finish();
      }
    })();

    return () => {
      closed = true;
      controller.abort();
    };
  },

  startBatch: (
    caseIds: number[],
    llmProvider?: string | null,
    options?: { enableVerifier?: boolean }
  ) =>
    request<{ batch_id: string; status: string; results: unknown[] }>("/batches", {
      method: "POST",
      body: JSON.stringify({
        case_ids: caseIds,
        enable_verifier: options?.enableVerifier ?? false,
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),

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
