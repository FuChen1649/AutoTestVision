import { api } from "./client";
import type { AgentLogItem, AgentRunState, CaseListItem, StreamEvent } from "../types/agent";

function toCaseListItem(
  item: Awaited<ReturnType<typeof api.listCases>>[number]
): CaseListItem {
  return {
    id: item.id!,
    name: item.name,
    step_count: item.steps?.length ?? 0,
    updated_at: item.updated_at ?? new Date().toISOString(),
  };
}

const API_BASE = "/api/agent-test";

function parseError(detail: string, status: number): string {
  try {
    const payload = JSON.parse(detail) as { detail?: string };
    if (payload.detail) {
      if (status === 404 && payload.detail === "Not Found") {
        return "Agent 接口未就绪，请关闭旧的后端窗口后重新运行 start.bat";
      }
      return payload.detail;
    }
  } catch {
    // ignore
  }
  return detail || `请求失败: ${status}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(parseError(detail, response.status));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
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

  startRun: (caseId: number) =>
    request<AgentRunState>("/runs", {
      method: "POST",
      body: JSON.stringify({ case_id: caseId, auto_run: false }),
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
};
