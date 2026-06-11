export type AppPageId =
  | "case-builder"
  | "agent-test"
  | "result"
  | "data-cleaning"
  | "data-flywheel";

export interface NavItem {
  id: AppPageId;
  label: string;
  description: string;
  dividerBefore?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: "case-builder",
    label: "自然语言 Case",
    description: "构建与保存自然语言描述的测试 Case",
  },
  {
    id: "agent-test",
    label: "AgentTest",
    description: "Agent 测试与执行",
  },
  {
    id: "result",
    label: "Result",
    description: "批量执行结果与回放",
  },
  {
    id: "data-cleaning",
    label: "数据清洗",
    description: "数据清洗（建设中）",
    dividerBefore: true,
  },
  {
    id: "data-flywheel",
    label: "数据飞轮",
    description: "数据飞轮（建设中）",
  },
];
