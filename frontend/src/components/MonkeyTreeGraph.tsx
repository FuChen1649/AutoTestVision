import { useMemo } from "react";
import type { MonkeyNode } from "../types/monkey";

interface MonkeyTreeGraphProps {
  nodes: MonkeyNode[];
  rootUuid: string;
  selectedNodeUuid: string | null;
  onSelectNode: (node: MonkeyNode) => void;
}

interface GraphLayoutNode {
  node: MonkeyNode;
  x: number;
  y: number;
}

const NODE_WIDTH = 120;
const NODE_HEIGHT = 36;
const LEVEL_GAP = 90;
const SIBLING_GAP = 24;

function layoutTree(nodes: MonkeyNode[], rootUuid: string): { layout: GraphLayoutNode[]; edges: Array<[string, string]> } {
  const byUuid = new Map(nodes.map((node) => [node.node_uuid, node]));
  const childrenByParent = new Map<string, MonkeyNode[]>();
  for (const node of nodes) {
    if (!node.parent_node_uuid) continue;
    const list = childrenByParent.get(node.parent_node_uuid) ?? [];
    list.push(node);
    childrenByParent.set(node.parent_node_uuid, list);
  }
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.title.localeCompare(b.title, "zh-CN"));
  }

  const layout: GraphLayoutNode[] = [];
  const edges: Array<[string, string]> = [];

  const measureWidth = (uuid: string): number => {
    const children = childrenByParent.get(uuid) ?? [];
    if (children.length === 0) {
      return NODE_WIDTH;
    }
    const total =
      children.reduce((sum, child) => sum + measureWidth(child.node_uuid), 0) +
      SIBLING_GAP * Math.max(children.length - 1, 0);
    return Math.max(NODE_WIDTH, total);
  };

  const place = (uuid: string, depth: number, left: number): number => {
    const node = byUuid.get(uuid);
    if (!node) return left;
    const children = childrenByParent.get(uuid) ?? [];
    const subtreeWidth = measureWidth(uuid);
    const centerX = left + subtreeWidth / 2;
    layout.push({ node, x: centerX, y: depth * LEVEL_GAP + 40 });

    if (children.length === 0) {
      return left + subtreeWidth;
    }

    let cursor = left;
    for (const child of children) {
      const childWidth = measureWidth(child.node_uuid);
      place(child.node_uuid, depth + 1, cursor);
      edges.push([uuid, child.node_uuid]);
      cursor += childWidth + SIBLING_GAP;
    }
    return left + subtreeWidth;
  };

  place(rootUuid, 0, 20);
  return { layout, edges };
}

export default function MonkeyTreeGraph({
  nodes,
  rootUuid,
  selectedNodeUuid,
  onSelectNode,
}: MonkeyTreeGraphProps) {
  const { layout, edges, width, height } = useMemo(() => {
    const result = layoutTree(nodes, rootUuid);
    const maxX = Math.max(...result.layout.map((item) => item.x), NODE_WIDTH) + NODE_WIDTH;
    const maxY = Math.max(...result.layout.map((item) => item.y), NODE_HEIGHT) + NODE_HEIGHT + 20;
    return { ...result, width: maxX, height: maxY };
  }, [nodes, rootUuid]);

  const byUuid = useMemo(() => new Map(layout.map((item) => [item.node.node_uuid, item])), [layout]);

  return (
    <div className="monkey-graph-wrap">
      <svg className="monkey-graph" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="探索树结构图">
        {edges.map(([from, to]) => {
          const source = byUuid.get(from);
          const target = byUuid.get(to);
          if (!source || !target) return null;
          return (
            <line
              key={`${from}-${to}`}
              x1={source.x}
              y1={source.y + NODE_HEIGHT / 2}
              x2={target.x}
              y2={target.y - NODE_HEIGHT / 2}
              stroke="#475569"
              strokeWidth={1.5}
            />
          );
        })}
        {layout.map(({ node, x, y }) => {
          const selected = selectedNodeUuid === node.node_uuid;
          return (
            <g
              key={node.node_uuid}
              transform={`translate(${x - NODE_WIDTH / 2}, ${y - NODE_HEIGHT / 2})`}
              className={`monkey-graph-node ${selected ? "selected" : ""}`}
              onClick={() => onSelectNode(node)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectNode(node);
                }
              }}
            >
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={8}
                fill={selected ? "#1d4ed8" : "#1e293b"}
                stroke={selected ? "#93c5fd" : "#334155"}
              />
              <text x={NODE_WIDTH / 2} y={NODE_HEIGHT / 2 + 4} textAnchor="middle" fill="#e2e8f0" fontSize="11">
                {node.title.length > 14 ? `${node.title.slice(0, 13)}…` : node.title}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
