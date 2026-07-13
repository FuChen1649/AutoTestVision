import { readApiResponse } from "./http";

const API_BASE = "/api/case-recording";

export type RecordingSessionStatus =
  | "recording"
  | "generating"
  | "review"
  | "saved"
  | "cancelled"
  | "failed";

export interface GeneratedStepDraft {
  step_order: number;
  description: string;
  event_uuid: string;
  screen_image_url?: string | null;
  screen_width?: number | null;
  screen_height?: number | null;
  selection_x?: number | null;
  selection_y?: number | null;
  selection_width?: number | null;
  selection_height?: number | null;
}

export interface RecordingEvent {
  event_uuid: string;
  step_order: number;
  action_type: string;
  x?: number | null;
  y?: number | null;
  x2?: number | null;
  y2?: number | null;
  duration_ms?: number | null;
  key_name?: string | null;
  before_image_url?: string | null;
  after_image_url?: string | null;
  device_width?: number | null;
  device_height?: number | null;
  element_hint?: string | null;
  created_at: string;
}

export interface RecordingSession {
  session_uuid: string;
  serial?: string | null;
  case_name: string;
  status: RecordingSessionStatus;
  llm_provider?: string | null;
  event_count: number;
  generated_steps: GeneratedStepDraft[];
  saved_case_id?: number | null;
  error?: string | null;
  events: RecordingEvent[];
  created_at: string;
  updated_at: string;
}

export interface RecordingLogItem {
  id: number;
  step_order?: number | null;
  log_type: string;
  message: string;
  detail?: Record<string, unknown> | null;
  created_at: string;
}

export interface RecordingLogsResponse {
  items: RecordingLogItem[];
  total: number;
}

export type RecordActionPayload =
  | { action_type: "tap"; x: number; y: number }
  | { action_type: "long_press"; x: number; y: number; duration_ms?: number }
  | { action_type: "swipe"; x: number; y: number; x2: number; y2: number; duration_ms?: number }
  | { action_type: "key"; key: "back" | "home" | "recents" };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const caseRecordingApi = {
  listProviders: () =>
    request<{ providers: { id: string; label: string; available: boolean }[] }>("/providers"),

  createSession: (payload: { serial?: string | null; case_name?: string; llm_provider?: string | null }) =>
    request<RecordingSession>("/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getSession: (sessionUuid: string) => request<RecordingSession>(`/sessions/${sessionUuid}`),

  getLogs: (sessionUuid: string, afterId = 0) =>
    request<RecordingLogsResponse>(
      `/sessions/${sessionUuid}/logs${afterId > 0 ? `?after_id=${afterId}` : ""}`
    ),

  recordAction: (sessionUuid: string, payload: RecordActionPayload) =>
    request<RecordingSession>(`/sessions/${sessionUuid}/actions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  stopRecording: (sessionUuid: string) =>
    request<RecordingSession>(`/sessions/${sessionUuid}/stop`, { method: "POST" }),

  confirmSave: (
    sessionUuid: string,
    payload: { case_name?: string; steps?: GeneratedStepDraft[] }
  ) =>
    request<{ case_id: number; case_name: string; step_count: number }>(
      `/sessions/${sessionUuid}/confirm`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    ),

  cancelSession: (sessionUuid: string) =>
    request<void>(`/sessions/${sessionUuid}/cancel`, { method: "POST" }),

  deleteSession: (sessionUuid: string) =>
    request<void>(`/sessions/${sessionUuid}`, { method: "DELETE" }),
};
