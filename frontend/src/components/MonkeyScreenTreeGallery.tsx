import { useMemo } from "react";
import type { MonkeyNode, MonkeyScreenAction } from "../types/monkey";

interface TreeNode {
  node: MonkeyNode;
  children: TreeNode[];
  actionNo: number | null;
}

interface MonkeyScreenTreeGalleryProps {
  treeNodes: MonkeyNode[];
  actions: MonkeyScreenAction[];
  selectedScreenUuid: string | null;
  focusScreenUuid: string | null;
  zoom: number;
  onSelectScreen: (node: MonkeyNode) => void;
  onPreviewScreen: (node: MonkeyNode) => void;
}

function imageUrlWithCache(url: string | null | undefined, updatedAt?: string) {
  if (!url) return null;
  if (!updatedAt) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}t=${encodeURIComponent(updatedAt)}`;
}

function buildTree(treeNodes: MonkeyNode[], actions: MonkeyScreenAction[]): TreeNode[] {
  const actionByElement = new Map<string, MonkeyScreenAction>();
  const actionByResult = new Map<string, MonkeyScreenAction>();
  for (const action of actions) {
    if (action.element_node_uuid) {
      actionByElement.set(action.element_node_uuid, action);
    }
    if (action.result_screen_uuid) {
      actionByResult.set(action.result_screen_uuid, action);
    }
  }

  const byParent = new Map<string | null, MonkeyNode[]>();
  for (const node of treeNodes) {
    const key = node.parent_node_uuid;
    const list = byParent.get(key) ?? [];
    list.push(node);
    byParent.set(key, list);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => {
      if (a.node_type === "element" && b.node_type === "element") {
        const aNo = actionByElement.get(a.node_uuid)?.action_no ?? 0;
        const bNo = actionByElement.get(b.node_uuid)?.action_no ?? 0;
        return aNo - bNo;
      }
      return a.depth - b.depth || a.created_at.localeCompare(b.created_at);
    });
  }

  const build = (parentUuid: string | null): TreeNode[] =>
    (byParent.get(parentUuid) ?? []).map((node) => {
      let actionNo: number | null = null;
      if (node.node_type === "element") {
        actionNo = actionByElement.get(node.node_uuid)?.action_no ?? null;
      } else if (node.node_type === "screen" && node.parent_node_uuid) {
        const parent = treeNodes.find((n) => n.node_uuid === node.parent_node_uuid);
        if (parent?.node_type === "element") {
          actionNo = actionByElement.get(parent.node_uuid)?.action_no ?? null;
        } else {
          actionNo = actionByResult.get(node.node_uuid)?.action_no ?? null;
        }
      }
      return {
        node,
        actionNo,
        children: build(node.node_uuid),
      };
    });

  return build(null);
}

function TreeNodeCard({
  item,
  actions,
  selectedScreenUuid,
  focusScreenUuid,
  onSelectScreen,
  onPreviewScreen,
}: {
  item: TreeNode;
  actions: MonkeyScreenAction[];
  selectedScreenUuid: string | null;
  focusScreenUuid: string | null;
  onSelectScreen: (node: MonkeyNode) => void;
  onPreviewScreen: (node: MonkeyNode) => void;
}) {
  const node = item.node;
  const isRoot = node.node_type === "root";
  const isElement = node.node_type === "element";
  const isScreen = node.node_type === "screen";
  const isSelected = selectedScreenUuid === node.node_uuid;

  const screenActions = isScreen
    ? actions.filter((a) => a.screen_node_uuid === node.node_uuid).sort((a, b) => a.action_no - b.action_no)
    : [];
  const pending = screenActions.filter((a) => a.status === "pending").length;
  const imageUrl = imageUrlWithCache(
    node.annotated_screenshot_url ?? node.screenshot_url,
    node.updated_at
  );

  if (isElement) {
    return (
      <div className="monkey-tree-node-wrap element">
        <button
          type="button"
          className={`monkey-tree-element-chip status-${node.status}`}
          onClick={() => onSelectScreen(node)}
          title={node.title}
        >
          <span className="monkey-tree-element-no">{item.actionNo ?? "?"}</span>
          <span className="monkey-tree-element-title">{node.title}</span>
        </button>
        {item.children.length > 0 && (
          <div className="monkey-tree-children-row">
            {item.children.map((child) => (
              <div key={child.node.node_uuid} className="monkey-tree-child-branch">
                <div className="monkey-tree-connector" />
                <TreeNodeCard
                  item={child}
                  actions={actions}
                  selectedScreenUuid={selectedScreenUuid}
                  focusScreenUuid={focusScreenUuid}
                  onSelectScreen={onSelectScreen}
                  onPreviewScreen={onPreviewScreen}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="monkey-tree-node-wrap">
      <div className={`monkey-tree-node-card ${isSelected ? "selected" : ""} ${isRoot ? "root" : ""}`}>
        {isScreen && (
          <button
            type="button"
            className="monkey-tree-node-media"
            onClick={() => onPreviewScreen(node)}
            title="点击放大查看标注"
          >
            {imageUrl ? (
              <img src={imageUrl} alt={node.title} loading="lazy" />
            ) : (
              <div className="monkey-tree-node-placeholder">无截图</div>
            )}
            <span className="monkey-tree-zoom-hint">点击放大</span>
          </button>
        )}
        <button
          type="button"
          className="monkey-tree-node-meta-btn"
          onClick={() => onSelectScreen(node)}
          title={node.title}
        >
          {isRoot && <span className="monkey-tree-root-icon">根</span>}
          <span className="monkey-tree-node-title">{node.title}</span>
          {item.actionNo != null && isScreen && node.parent_node_uuid && (
            <span className="monkey-tree-via-badge">经 #{item.actionNo}</span>
          )}
          {pending > 0 && <span className="monkey-tree-pending-badge">{pending} 待探索</span>}
          {focusScreenUuid === node.node_uuid && (
            <span className="monkey-tree-exploring-badge">真机探索中</span>
          )}
        </button>
      </div>

      {item.children.length > 0 && (
        <div className="monkey-tree-children-row">
          {item.children.map((child) => (
            <div key={child.node.node_uuid} className="monkey-tree-child-branch">
              <div className="monkey-tree-connector" />
              <TreeNodeCard
                item={child}
                actions={actions}
                selectedScreenUuid={selectedScreenUuid}
                focusScreenUuid={focusScreenUuid}
                onSelectScreen={onSelectScreen}
                onPreviewScreen={onPreviewScreen}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MonkeyScreenTreeGallery({
  treeNodes,
  actions,
  selectedScreenUuid,
  zoom,
  focusScreenUuid,
  onSelectScreen,
  onPreviewScreen,
}: MonkeyScreenTreeGalleryProps) {
  const roots = useMemo(() => buildTree(treeNodes, actions), [treeNodes, actions]);

  if (treeNodes.length === 0) {
    return <div className="monkey-tree-empty">开始探索后，屏幕树将在此展示</div>;
  }

  return (
    <div className="monkey-screen-tree" style={{ transform: `scale(${zoom})`, transformOrigin: "top center" }}>
      {roots.map((root) => (
        <div key={root.node.node_uuid} className="monkey-screen-tree-root">
          <TreeNodeCard
            item={root}
            actions={actions}
            selectedScreenUuid={selectedScreenUuid}
            focusScreenUuid={focusScreenUuid}
            onSelectScreen={onSelectScreen}
            onPreviewScreen={onPreviewScreen}
          />
        </div>
      ))}
      <div className="monkey-tree-legend">
        屏幕节点显示累加标注截图；元素子节点（#1 #2）挂在屏幕下；本屏探索完再展开子屏幕
      </div>
    </div>
  );
}
