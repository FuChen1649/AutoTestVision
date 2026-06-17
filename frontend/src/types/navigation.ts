export type AppPageId =
  | "case-builder"
  | "agent-test-position"
  | "agent-test-code"
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
    id: "agent-test-position",
    label: "AgentTest_Position",
    description: "坐标意图分析 + 触控执行",
  },
  {
    id: "agent-test-code",
    label: "AgentTest_Code",
    description: "代码意图分析 + uiautomator2/pytest 执行",
  },
  {
    id: "result",
    label: "Result",
    description: "批量执行结果与回放",
  },
  {
    id: "data-cleaning",
    label: "数据清洗",
    description: "样本同步、自动清洗与人工标注",
    dividerBefore: true,
  },
  {
    id: "data-flywheel",
    label: "数据飞轮",
    description: "数据集、RAG、训练与评估",
  },
];
