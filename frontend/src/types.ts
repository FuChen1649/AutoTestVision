export type CaseStepType = "natural" | "permission_preset";

export interface StepScreenBinding {
  screen_image: string;
  screen_width: number;
  screen_height: number;
  selection_x: number;
  selection_y: number;
  selection_width: number;
  selection_height: number;
}

export interface CaseStep {
  id?: number;
  case_id?: number;
  step_order: number;
  step_type?: CaseStepType;
  description: string;
  screen_image?: string | null;
  screen_width?: number | null;
  screen_height?: number | null;
  selection_x?: number | null;
  selection_y?: number | null;
  selection_width?: number | null;
  selection_height?: number | null;
}

export interface CaseData {
  id?: number;
  name: string;
  script_content: string;
  steps: CaseStep[];
  created_at?: string;
  updated_at?: string;
}

export interface DeviceInfo {
  serial: string;
  model: string;
  product: string;
  screen_width: number;
  screen_height: number;
  connected: boolean;
}

export interface ScreenFrame {
  type: "frame" | "error";
  image?: string;
  width?: number;
  height?: number;
  message?: string;
}

export interface AppInfo {
  package: string;
  label: string;
  category: string;
}

export interface AppPermissionInfo {
  name: string;
  label: string;
  granted: boolean | null;
  revocable: boolean;
  group: string;
}

export interface PermissionApplyResult {
  package: string;
  granted: string[];
  revoked: string[];
  skipped: string[];
  errors: string[];
}
