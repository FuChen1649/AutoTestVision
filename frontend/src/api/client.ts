import { readApiResponse } from "./http";
import type { AppInfo, AppPermissionInfo, CaseData, DeviceInfo, PermissionApplyResult } from "../types";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  return readApiResponse<T>(response);
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  listCases: () => request<CaseData[]>("/cases"),

  createCase: (payload: CaseData) =>
    request<CaseData>("/cases", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateCase: (id: number, payload: Partial<CaseData>) =>
    request<CaseData>(`/cases/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteCase: (id: number) => request<void>(`/cases/${id}`, { method: "DELETE" }),

  listDevices: () => request<DeviceInfo[]>("/device/list"),

  selectDevice: (serial: string) =>
    request<{ serial: string }>(`/device/select/${serial}`, { method: "POST" }),

  getScreenshot: (serial?: string) => {
    const query = serial ? `?serial=${encodeURIComponent(serial)}` : "";
    return request<{ image: string; width: number; height: number }>(`/device/screenshot${query}`);
  },

  tap: (x: number, y: number, serial?: string) =>
    request<{ status: string }>("/device/tap", {
      method: "POST",
      body: JSON.stringify({ x, y, serial }),
    }),

  swipe: (
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    durationMs = 300,
    serial?: string
  ) =>
    request<{ status: string }>("/device/swipe", {
      method: "POST",
      body: JSON.stringify({ x1, y1, x2, y2, duration_ms: durationMs, serial }),
    }),

  longPress: (x: number, y: number, durationMs = 800, serial?: string) =>
    request<{ status: string }>("/device/long-press", {
      method: "POST",
      body: JSON.stringify({ x, y, duration_ms: durationMs, serial }),
    }),

  listApps: (serial?: string) => {
    const query = serial ? `?serial=${encodeURIComponent(serial)}` : "";
    return request<AppInfo[]>(`/device/apps${query}`);
  },

  getAppPermissions: (packageName: string, serial?: string) => {
    const query = serial ? `?serial=${encodeURIComponent(serial)}` : "";
    return request<AppPermissionInfo[]>(`/device/apps/${encodeURIComponent(packageName)}/permissions${query}`);
  },

  applyAppPermissions: (packageName: string, selectedPermissions: string[], serial?: string) =>
    request<PermissionApplyResult>(
      `/device/apps/${encodeURIComponent(packageName)}/permissions/apply`,
      {
        method: "POST",
        body: JSON.stringify({ selected_permissions: selectedPermissions, serial }),
      }
    ),
};

export function createScreenStream(serial?: string, fps = 5): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  const params = new URLSearchParams({ fps: String(fps) });
  if (serial) {
    params.set("serial", serial);
  }
  return new WebSocket(`${protocol}://${host}/api/device/stream?${params.toString()}`);
}
