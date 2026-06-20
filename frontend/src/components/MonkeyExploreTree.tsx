import { useMemo, useState } from "react";
import type { MonkeyNode } from "../types/monkey";

interface TreeNode {
  node: MonkeyNode;
  children: TreeNode[];
}

interface MonkeyExploreTreeProps {
  nodes: MonkeyNode[];
  selectedNodeUuid: string | null;
  onSelectNode: (node: MonkeyNode) => void;
  onSelectRoot: (node: MonkeyNode) => void;
}

const TYPE_ICON: Record<string, string> = {
  root: "📁",
  screen: "🖥",
  app: "📱",
  element: "🔘",
  container: "📦",
};

function buildTree(nodes: MonkeyNode[]): TreeNode[] {
  const byParent = new Map<string | null, MonkeyNode[]>();
  for (const node of nodes) {
    const key = node.parent_node_uuid;
    const list = byParent.get(key) ?? [];
    list.push(node);
    byParent.set(key, list);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.title.localeCompare(b.title, "zh-CN"));
  }

  const build = (parentUuid: string | null): TreeNode[] =>
    (byParent.get(parentUuid) ?? []).map((node) => ({
      node,
      children: build(node.node_uuid),
    }));

  return build(null);
}

function TreeRow({
  item,
  depth,
  selectedNodeUuid,
  expanded,
  onToggle,
  onSelectNode,
  onSelectRoot,
}: {
  item: TreeNode;
  depth: number;
  selectedNodeUuid: string | null;
  expanded: Set<string>;
  onToggle: (uuid: string) => void;
  onSelectNode: (node: MonkeyNode) => void;
  onSelectRoot: (node: MonkeyNode) => void;
}) {
  const hasChildren = item.children.length > 0;
  const isExpanded = expanded.has(item.node.node_uuid);
  const isSelected = selectedNodeUuid === item.node.node_uuid;
  const isRoot = item.node.node_type === "root";

  return (
    <div className="monkey-tree-branch">
      <div
        className={`monkey-tree-row ${isSelected ? "selected" : ""}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            className="monkey-tree-toggle"
            aria-label={isExpanded ? "折叠" : "展开"}
            onClick={() => onToggle(item.node.node_uuid)}
          >
            {isExpanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="monkey-tree-toggle placeholder" />
        )}
        <button
          type="button"
          className="monkey-tree-label"
          onClick={() => {
            onSelectNode(item.node);
            if (isRoot) {
              onSelectRoot(item.node);
            }
          }}
        >
          <span className="monkey-tree-icon">{TYPE_ICON[item.node.node_type] ?? "•"}</span>
          <span className="monkey-tree-title">{item.node.title}</span>
          <span className={`monkey-tree-status status-${item.node.status}`}>{item.node.status}</span>
        </button>
      </div>
      {hasChildren && isExpanded && (
        <div className="monkey-tree-children">
          {item.children.map((child) => (
            <TreeRow
              key={child.node.node_uuid}
              item={child}
              depth={depth + 1}
              selectedNodeUuid={selectedNodeUuid}
              expanded={expanded}
              onToggle={onToggle}
              onSelectNode={onSelectNode}
              onSelectRoot={onSelectRoot}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function MonkeyExploreTree({
  nodes,
  selectedNodeUuid,
  onSelectNode,
  onSelectRoot,
}: MonkeyExploreTreeProps) {
  const roots = useMemo(() => buildTree(nodes), [nodes]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.map((n) => n.node_uuid)));

  const toggle = (uuid: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(uuid)) {
        next.delete(uuid);
      } else {
        next.add(uuid);
      }
      return next;
    });
  };

  if (nodes.length === 0) {
    return <div className="monkey-tree-empty">暂无探索节点，开始探索后将在此展示目录树</div>;
  }

  return (
    <div className="monkey-tree">
      {roots.map((item) => (
        <TreeRow
          key={item.node.node_uuid}
          item={item}
          depth={0}
          selectedNodeUuid={selectedNodeUuid}
          expanded={expanded}
          onToggle={toggle}
          onSelectNode={onSelectNode}
          onSelectRoot={onSelectRoot}
        />
      ))}
    </div>
  );
}
