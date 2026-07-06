import { readApiResponse } from "./http";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export interface CaseListItem {
  id: number;
  name: string;
  script_content: string;
  step_count: number;
  script_status: string | null;
  last_run_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseListPage {
  items: CaseListItem[];
  total: number;
  page: number;
  size: number;
}

export const casesApi = {
  list: (params?: { q?: string; page?: number; size?: number }) => {
    const search = new URLSearchParams();
    if (params?.q) search.set("q", params.q);
    if (params?.page) search.set("page", String(params.page));
    if (params?.size) search.set("size", String(params.size));
    const qs = search.toString();
    return request<CaseListPage>(`/cases${qs ? `?${qs}` : ""}`);
  },
};

export interface TaskProgress {
  completed_steps: number;
  total_steps: number;
  current_step?: number | null;
  message?: string | null;
}

export interface PlatformTask {
  task_uuid: string;
  task_type: string;
  exec_mode: string | null;
  source_case_id: number | null;
  case_name: string | null;
  ref_uuid: string | null;
  parent_task_uuid: string | null;
  status: string;
  progress: TaskProgress;
  serial: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  detail_path: string | null;
}

export interface TaskListResponse {
  items: PlatformTask[];
  total: number;
}

export const tasksApi = {
  list: (params?: { task_type?: string; status?: string; case_id?: number; limit?: number; offset?: number }) => {
    const search = new URLSearchParams();
    if (params?.task_type) search.set("task_type", params.task_type);
    if (params?.status) search.set("status", params.status);
    if (params?.case_id != null) search.set("case_id", String(params.case_id));
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.offset) search.set("offset", String(params.offset));
    const qs = search.toString();
    return request<TaskListResponse>(`/tasks${qs ? `?${qs}` : ""}`);
  },
  get: (taskUuid: string) => request<PlatformTask>(`/tasks/${taskUuid}`),
  cancel: (taskUuid: string) =>
    request<{ task_uuid: string; status: string; message: string }>(`/tasks/${taskUuid}/cancel`, {
      method: "POST",
    }),
};

export interface DualScriptStep {
  step_order: number;
  step_type: string;
  description: string;
  script_status: string | null;
  position_script: Record<string, unknown> | null;
  code_script: Record<string, unknown> | null;
  script_generated_at: string | null;
}

export interface CaseScriptsResponse {
  case_id: number;
  case_name: string;
  script_status: string | null;
  steps: DualScriptStep[];
}

export interface ScriptGenPrerequisites {
  ready: boolean;
  min_devices: number;
  device_count: number;
  devices: { serial: string; model: string; connected: boolean }[];
  position_serial: string | null;
  code_serial: string | null;
  message: string;
}

export const scriptGenApi = {
  checkPrerequisites: (params?: { position_serial?: string; code_serial?: string }) => {
    const search = new URLSearchParams();
    if (params?.position_serial) search.set("position_serial", params.position_serial);
    if (params?.code_serial) search.set("code_serial", params.code_serial);
    const qs = search.toString();
    return request<ScriptGenPrerequisites>(`/script-generation/prerequisites${qs ? `?${qs}` : ""}`);
  },
  getScripts: (caseId: number) => request<CaseScriptsResponse>(`/cases/${caseId}/scripts`),
  start: (
    caseId: number,
    payload?: { position_serial?: string; code_serial?: string; llm_provider?: string }
  ) =>
    request<{ task_uuid: string; case_id: number; status: string }>(`/cases/${caseId}/generate-scripts`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    }),
  stream: (taskUuid: string, onEvent: (event: Record<string, unknown>) => void) => {
    const source = new EventSource(`/api/script-generation/${taskUuid}/stream`);
    source.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch {
        // ignore
      }
    };
    return () => source.close();
  },
};

export interface ReportSummary {
  report_id: string;
  report_type: string;
  exec_mode: string;
  status: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  completed_cases: number;
  serial: string | null;
  case_id?: number | null;
  case_name?: string | null;
  run_uuid?: string | null;
  position_run_uuid?: string | null;
  code_run_uuid?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReportCaseResult {
  case_id: number;
  case_name: string;
  status: string;
  run_uuid: string;
  total_steps: number;
  passed_steps: number;
  error?: string | null;
  exec_mode?: string;
  path_label?: string;
}

export interface ReportDetail {
  report_id: string;
  report_type: string;
  exec_mode: string;
  status: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  completed_cases: number;
  case_id?: number | null;
  case_name?: string | null;
  run_uuid?: string | null;
  case_results: ReportCaseResult[];
  dual_reviews?: DualStepVerifyReview[];
  created_at: string;
  updated_at: string;
}

export interface DualStepVerifyReview {
  step_order: number;
  consistent: boolean;
  before_match: boolean;
  after_match: boolean;
  purpose: string;
  reasoning: string;
  confidence?: number;
  model?: string | null;
  reviewed_at: string;
}

export const reportsApi = {
  list: (execMode?: string) => {
    const qs = execMode ? `?exec_mode=${encodeURIComponent(execMode)}` : "";
    return request<{ items: ReportSummary[]; total: number }>(`/reports${qs}`);
  },
  get: (reportId: string, execMode = "position") =>
    request<ReportDetail>(`/reports/${reportId}?exec_mode=${execMode}`),
  getRun: (runUuid: string, execMode = "position") =>
    request<Record<string, unknown>>(`/reports/runs/${runUuid}?exec_mode=${execMode}`),
};

export interface LogEntry {
  id: number;
  source: string;
  run_uuid: string | null;
  session_uuid: string | null;
  step_order: number | null;
  agent_type: string;
  message: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export const logsApi = {
  list: (params?: { source?: string; run_uuid?: string; limit?: number; offset?: number }) => {
    const search = new URLSearchParams();
    if (params?.source) search.set("source", params.source);
    if (params?.run_uuid) search.set("run_uuid", params.run_uuid);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.offset) search.set("offset", String(params.offset));
    const qs = search.toString();
    return request<{ items: LogEntry[]; total: number }>(`/logs${qs ? `?${qs}` : ""}`);
  },
};

export interface UnifiedBatchResponse {
  exec_mode: string;
  task_uuid: string | null;
  position_batch: Record<string, unknown> | null;
  code_batch: Record<string, unknown> | null;
}

export const batchApi = {
  start: (payload: {
    case_ids: number[];
    exec_mode: "position" | "code" | "dual";
    serial?: string;
    llm_provider?: string;
    enable_verifier?: boolean;
  }) =>
    request<UnifiedBatchResponse>("/batch", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
