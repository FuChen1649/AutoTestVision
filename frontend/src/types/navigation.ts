export type AppPageId = "case-builder" | "agent-test";

export interface NavItem {
  id: AppPageId;
  label: string;
  description: string;
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
];
