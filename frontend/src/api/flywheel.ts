import { readApiResponse } from "./http";
import type {
  AnnotationPayload,
  FlywheelDataset,
  FlywheelEvalJob,
  FlywheelRagDocument,
  FlywheelSample,
  FlywheelSampleListResponse,
  FlywheelStats,
  FlywheelTrainingJob,
  TrainingConfig,
} from "../types/flywheel";

const BASE = "/api/flywheel";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const flywheelApi = {
  getStats: () => request<FlywheelStats>("/stats"),

  syncSamples: (payload?: { limit_runs?: number; only_success_steps?: boolean }) =>
    request<{ synced: number; created: number; updated: number }>("/sync", {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    }),

  listSamples: (params?: {
    cleaning_status?: string;
    golden_only?: boolean;
    min_quality?: number;
    offset?: number;
    limit?: number;
    include_images?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.cleaning_status) query.set("cleaning_status", params.cleaning_status);
    if (params?.golden_only) query.set("golden_only", "true");
    if (params?.min_quality != null) query.set("min_quality", String(params.min_quality));
    if (params?.offset != null) query.set("offset", String(params.offset));
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.include_images) query.set("include_images", "true");
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<FlywheelSampleListResponse>(`/samples${suffix}`);
  },

  getSample: (sampleId: number) => request<FlywheelSample>(`/samples/${sampleId}`),

  annotateSample: (sampleId: number, payload: AnnotationPayload) =>
    request(`/samples/${sampleId}/annotation`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  cleanSample: (
    sampleId: number,
    payload: { cleaning_status: string; cleaning_notes?: string; exclude_reason?: string }
  ) =>
    request<FlywheelSample>(`/samples/${sampleId}/cleaning`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  bulkClean: (payload: { sample_ids: number[]; cleaning_status: string; cleaning_notes?: string }) =>
    request<{ updated: number }>("/cleaning/bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  autoClean: (payload: {
    min_quality_score?: number;
    require_both_images?: boolean;
    require_auto_verification?: boolean;
    dedupe?: boolean;
  }) =>
    request<{ marked_cleaned: number; marked_rejected: number; deduped: number }>("/cleaning/auto", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createDataset: (payload: {
    name: string;
    description?: string;
    dataset_type?: string;
    sample_ids?: number[];
    golden_only?: boolean;
    cleaning_statuses?: string[];
  }) =>
    request<FlywheelDataset>("/datasets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listDatasets: () => request<{ items: FlywheelDataset[] }>("/datasets"),

  generateRag: (payload: {
    dataset_id?: number;
    golden_only?: boolean;
    use_llm_summary?: boolean;
    llm_provider?: string;
  }) =>
    request<{ items: FlywheelRagDocument[]; export_path: string | null }>("/rag/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listRag: (datasetId?: number) => {
    const suffix = datasetId ? `?dataset_id=${datasetId}` : "";
    return request<{ items: FlywheelRagDocument[]; export_path?: string | null }>(`/rag${suffix}`);
  },

  createTrainingJob: (payload: { name: string; dataset_id: number; config?: TrainingConfig }) =>
    request<FlywheelTrainingJob>("/training/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listTrainingJobs: () => request<{ items: FlywheelTrainingJob[] }>("/training/jobs"),

  getTrainingJob: (jobUuid: string) => request<FlywheelTrainingJob>(`/training/jobs/${jobUuid}`),

  startTrainingJob: (jobUuid: string) =>
    request<FlywheelTrainingJob>(`/training/jobs/${jobUuid}/start`, { method: "POST" }),

  createEvalJob: (payload: {
    name: string;
    dataset_id: number;
    training_job_id?: number;
    llm_provider?: string;
    model_ref?: string;
  }) =>
    request<FlywheelEvalJob>("/eval/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listEvalJobs: () => request<{ items: FlywheelEvalJob[] }>("/eval/jobs"),

  getEvalJob: (jobUuid: string) => request<FlywheelEvalJob>(`/eval/jobs/${jobUuid}`),

  startEvalJob: (jobUuid: string) =>
    request<FlywheelEvalJob>(`/eval/jobs/${jobUuid}/start`, { method: "POST" }),
};
