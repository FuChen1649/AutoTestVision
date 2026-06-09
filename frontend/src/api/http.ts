/** 后端/网络不可达，界面应显示「未连接」而非错误详情 */
export class ApiOfflineError extends Error {
  constructor() {
    super("offline");
    this.name = "ApiOfflineError";
  }
}

export function isApiOfflineError(error: unknown): boolean {
  return error instanceof ApiOfflineError;
}

function isHtmlBody(text: string): boolean {
  const trimmed = text.trimStart().toLowerCase();
  return trimmed.startsWith("<!doctype") || trimmed.startsWith("<html");
}

function logApiIssue(label: string, detail: string, status?: number) {
  console.warn(`[API] ${label}`, status ?? "", detail.slice(0, 300));
}

function throwOffline(label: string, detail: string, status?: number): never {
  logApiIssue(label, detail, status);
  throw new ApiOfflineError();
}

export function formatApiError(detail: string, status: number): string {
  const trimmed = detail.trim();

  if (!trimmed || isHtmlBody(trimmed)) {
    throwOffline("non-json error body", trimmed, status);
  }

  if (status === 502 || status === 503 || status === 504) {
    throwOffline("service unavailable", trimmed, status);
  }

  try {
    const payload = JSON.parse(trimmed) as { detail?: string };
    if (payload.detail) {
      if (
        payload.detail.includes("start.bat") ||
        payload.detail.includes("后端服务") ||
        payload.detail === "Not Found"
      ) {
        throwOffline("proxy/backend", trimmed, status);
      }
      return payload.detail;
    }
  } catch (error) {
    if (error instanceof ApiOfflineError) {
      throw error;
    }
  }

  return trimmed.length > 120 ? `${trimmed.slice(0, 120)}...` : trimmed || `请求失败: ${status}`;
}

export async function readApiResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "";

  if (!response.ok) {
    throw new Error(formatApiError(text, response.status));
  }

  if (response.status === 204 || text.length === 0) {
    return undefined as T;
  }

  if (isHtmlBody(text) || (!contentType.includes("application/json") && text.trimStart().startsWith("<"))) {
    throwOffline("html success body", text, response.status);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throwOffline("invalid json", text, response.status);
  }
}
