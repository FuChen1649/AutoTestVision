import type { AgentRunState } from "./agent";

export type CaseAgentExecMode = "position" | "code";

/** 从自然语言 Case 保存后跳转到 AgentTest 页时携带的上下文 */
export interface AgentTestBootstrap {
  caseId: number;
  runId: string;
  mode: CaseAgentExecMode;
  run?: AgentRunState;
}

export interface NavItem {
  path: string;
  label: string;
  description: string;
  /** 用于高亮匹配的前缀 */
  matchPrefix?: string;
}

export interface NavGroup {
  id: string;
  title: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "core",
    title: "核心测试",
    items: [
      { path: "/cases", label: "Case 管理", description: "列表、创建与编辑测试 Case", matchPrefix: "/cases" },
      { path: "/tasks", label: "任务中心", description: "统一查看与管理执行任务", matchPrefix: "/tasks" },
      {
        path: "/agent/execute",
        label: "执行工作台",
        description: "Dual / Position / Code 生成与执行",
        matchPrefix: "/agent/execute",
      },
      { path: "/batch", label: "跑批管理", description: "批量执行 Case 任务", matchPrefix: "/batch" },
      { path: "/reports", label: "报告中心", description: "批量与单次执行报告", matchPrefix: "/reports" },
      { path: "/logs", label: "日志中心", description: "集中查询执行日志", matchPrefix: "/logs" },
    ],
  },
  {
    id: "infra",
    title: "基础设施",
    items: [
      { path: "/devices", label: "设备管理", description: "ADB 设备连接与状态", matchPrefix: "/devices" },
      { path: "/resources", label: "资源依赖", description: "测试资源与依赖（即将上线）", matchPrefix: "/resources" },
    ],
  },
  {
    id: "advanced",
    title: "高级 / 数据",
    items: [
      { path: "/monkey", label: "AgentMonkeyTest", description: "应用探索与树形导航", matchPrefix: "/monkey" },
      { path: "/data/cleaning", label: "数据清洗", description: "样本同步与人工标注", matchPrefix: "/data/cleaning" },
      { path: "/data/flywheel", label: "数据飞轮", description: "数据集、RAG 与训练", matchPrefix: "/data/flywheel" },
    ],
  },
];

export function isNavActive(pathname: string, item: NavItem): boolean {
  const prefix = item.matchPrefix ?? item.path;
  if (prefix === "/cases") {
    return pathname === "/cases" || pathname.startsWith("/cases/");
  }
  if (prefix === "/agent/execute") {
    // Dual 双脚本生成挂在执行工作台下，共用高亮
    return pathname.startsWith("/agent/execute") || pathname.startsWith("/agent/generate");
  }
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}
