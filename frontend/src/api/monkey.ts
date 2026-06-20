import { readApiResponse } from "./http";
import type {
  CreateMonkeySessionPayload,
  MonkeyProvidersResponse,
  MonkeySession,
  MonkeyStreamEvent,
  MonkeyTree,
} from "../types/monkey";

const API_BASE = "/api/agent-monkey";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const monkeyApi = {
  listProviders: () => request<MonkeyProvidersResponse>("/providers"),

  createSession: (payload: CreateMonkeySessionPayload) =>
    request<MonkeySession>("/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listSessions: (limit = 20) =>
    request<MonkeySession[]>(`/sessions?limit=${encodeURIComponent(String(limit))}`),

  getSession: (sessionUuid: string) => request<MonkeySession>(`/sessions/${sessionUuid}`),

  getTree: (sessionUuid: string) => request<MonkeyTree>(`/sessions/${sessionUuid}/tree`),

  stopSession: (sessionUuid: string) =>
    request<void>(`/sessions/${sessionUuid}/stop`, { method: "POST" }),

  deleteSession: (sessionUuid: string) =>
    request<void>(`/sessions/${sessionUuid}`, { method: "DELETE" }),

  streamExplore: (
    sessionUuid: string,
    handlers: {
      onEvent: (event: MonkeyStreamEvent) => void;
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
        const response = await fetch(`${API_BASE}/sessions/${sessionUuid}/start`, {
          method: "POST",
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!response.ok) {
          throw new Error(`探索流连接失败 (${response.status})`);
        }
        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("探索流不可读");
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
            const event = JSON.parse(payload) as MonkeyStreamEvent;
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
        handlers.onError?.(error instanceof Error ? error : new Error("探索流连接中断"));
        finish();
      }
    })();

    return () => {
      closed = true;
      controller.abort();
    };
  },
};
