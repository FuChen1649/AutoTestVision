export type MonkeyNodeType = "root" | "screen" | "app" | "element" | "container";
export type MonkeyNodeStatus = "discovered" | "explored" | "exploring" | "skipped" | "failed";
export type MonkeySessionStatus = "idle" | "running" | "stopped" | "completed" | "failed";

export interface MonkeyBBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface MonkeyCenter {
  x: number;
  y: number;
}

export interface MonkeyNode {
  node_uuid: string;
  parent_node_uuid: string | null;
  node_type: MonkeyNodeType;
  title: string;
  description?: string | null;
  screenshot_url?: string | null;
  annotated_screenshot_url?: string | null;
  bbox?: MonkeyBBox | null;
  center?: MonkeyCenter | null;
  screen_width?: number | null;
  screen_height?: number | null;
  screen_fingerprint?: string | null;
  status: MonkeyNodeStatus;
  depth: number;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface MonkeySession {
  session_uuid: string;
  serial?: string | null;
  target_app_name: string;
  status: MonkeySessionStatus;
  llm_provider?: string | null;
  step_count: number;
  max_steps: number;
  max_depth: number;
  current_node_uuid?: string | null;
  focus_screen_uuid?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonkeyTree {
  session_uuid: string;
  nodes: MonkeyNode[];
}

export type MonkeyActionStatus = "pending" | "executed" | "failed" | "skipped" | "no_effect";

export interface MonkeyScreenAction {
  action_uuid: string;
  screen_node_uuid: string;
  action_no: number;
  element_title: string;
  action_type: string;
  bbox?: MonkeyBBox | null;
  center?: MonkeyCenter | null;
  data_dependency?: string | null;
  status: MonkeyActionStatus;
  result_screen_uuid?: string | null;
  element_node_uuid?: string | null;
  step_index?: number | null;
  created_at: string;
  updated_at: string;
}

export interface MonkeyExploreState {
  session_uuid: string;
  session: MonkeySession;
  screens: MonkeyNode[];
  tree_nodes: MonkeyNode[];
  actions: MonkeyScreenAction[];
  logs: MonkeyLogItem[];
}

export interface MonkeyLogsResponse {
  session_uuid: string;
  logs: MonkeyLogItem[];
  latest_id: number;
}

export interface MonkeyLogItem {
  id: number;
  step_index?: number | null;
  log_type: string;
  message: string;
  detail?: Record<string, unknown> | null;
  created_at: string;
}

export interface MonkeyStreamEvent {
  type: string;
  session?: MonkeySession | null;
  nodes?: MonkeyNode[];
  screens?: MonkeyNode[];
  actions?: MonkeyScreenAction[];
  logs?: MonkeyLogItem[];
  message?: string | null;
}

export interface MonkeyProviderInfo {
  id: string;
  label: string;
  model: string;
  base_url: string;
  available: boolean;
}

export interface MonkeyProvidersResponse {
  providers: MonkeyProviderInfo[];
  default?: string | null;
}

export interface CreateMonkeySessionPayload {
  target_app_name: string;
  serial?: string | null;
  llm_provider?: string | null;
  max_steps?: number;
  max_depth?: number;
}
