import { readApiResponse } from "./http";
import type { RunPurposeReview, BatchPurposeReview, VerifyStreamEvent } from "../types/resultVerify";

const API_BASE = "/api/result-verify";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

function buildStreamUrl(path: string, llmProvider?: string | null) {
  const query = llmProvider ? `?llm_provider=${encodeURIComponent(llmProvider)}` : "";
  return `${API_BASE}${path}${query}`;
}

function openVerifyStream(
  url: string,
  handlers: {
    onEvent: (event: VerifyStreamEvent) => void;
    onError?: (error: Error) => void;
    onDone?: () => void;
  }
) {
  const source = new EventSource(url);

  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as VerifyStreamEvent;
      handlers.onEvent(event);
      if (event.type === "done" || event.type === "error") {
        source.close();
        handlers.onDone?.();
      }
    } catch (error) {
      handlers.onError?.(error instanceof Error ? error : new Error("验证流数据解析失败"));
    }
  };

  source.onerror = () => {
    source.close();
    handlers.onError?.(new Error("验证流连接中断，请确认后端已重启"));
    handlers.onDone?.();
  };

  return () => source.close();
}

export const resultVerifyApi = {
  verifyRun: (runId: string, llmProvider?: string | null) =>
    request<RunPurposeReview>(`/runs/${runId}`, {
      method: "POST",
      body: JSON.stringify({
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),

  streamVerifyRun: (
    runId: string,
    llmProvider: string | null | undefined,
    handlers: {
      onEvent: (event: VerifyStreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    }
  ) => openVerifyStream(buildStreamUrl(`/runs/${runId}/stream`, llmProvider), handlers),

  streamVerifyBatch: (
    batchId: string,
    llmProvider: string | null | undefined,
    handlers: {
      onEvent: (event: VerifyStreamEvent) => void;
      onError?: (error: Error) => void;
      onDone?: () => void;
    }
  ) => openVerifyStream(buildStreamUrl(`/batches/${batchId}/stream`, llmProvider), handlers),

  getRunReviews: (runId: string) => request<RunPurposeReview>(`/runs/${runId}`),

  verifyBatch: (batchId: string, llmProvider?: string | null) =>
    request<BatchPurposeReview>(`/batches/${batchId}`, {
      method: "POST",
      body: JSON.stringify({
        ...(llmProvider ? { llm_provider: llmProvider } : {}),
      }),
    }),
};
