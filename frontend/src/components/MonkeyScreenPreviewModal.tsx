import { useEffect } from "react";
import type { MonkeyNode, MonkeyScreenAction } from "../types/monkey";

interface MonkeyScreenPreviewModalProps {
  screen: MonkeyNode;
  actions: MonkeyScreenAction[];
  screens: MonkeyNode[];
  onClose: () => void;
}

function actionTypeLabel(type: string) {
  if (type === "long_press") return "长按";
  if (type === "swipe") return "滑动";
  return "点击";
}

function statusLabel(status: string) {
  if (status === "executed") return "已执行";
  if (status === "failed") return "失败";
  if (status === "skipped") return "跳过";
  return "待执行";
}

export default function MonkeyScreenPreviewModal({
  screen,
  actions,
  screens,
  onClose,
}: MonkeyScreenPreviewModalProps) {
  const imageUrl = (() => {
    const raw = screen.annotated_screenshot_url ?? screen.screenshot_url;
    if (!raw) return null;
    const sep = raw.includes("?") ? "&" : "?";
    return `${raw}${sep}t=${encodeURIComponent(screen.updated_at)}`;
  })();
  const screenActions = actions
    .filter((a) => a.screen_node_uuid === screen.node_uuid)
    .sort((a, b) => a.action_no - b.action_no);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="monkey-preview-overlay" onClick={onClose} role="presentation">
      <div
        className="monkey-preview-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`${screen.title} 标注预览`}
      >
        <div className="monkey-preview-header">
          <h3>{screen.title}</h3>
          <button type="button" className="monkey-preview-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="monkey-preview-body">
          <div className="monkey-preview-image-pane">
            {imageUrl ? (
              <img src={imageUrl} alt={screen.title} className="monkey-preview-image" />
            ) : (
              <div className="monkey-tree-empty">无截图</div>
            )}
          </div>
          <aside className="monkey-preview-side">
            <div className="monkey-preview-side-title">标注编号说明</div>
            {screenActions.length === 0 ? (
              <div className="monkey-tree-empty">该屏幕暂无编号操作</div>
            ) : (
              <ul className="monkey-preview-action-list">
                {screenActions.map((action) => {
                  const resultTitle = action.result_screen_uuid
                    ? screens.find((s) => s.node_uuid === action.result_screen_uuid)?.title
                    : null;
                  return (
                    <li key={action.action_uuid} className={`monkey-preview-action-item status-${action.status}`}>
                      <span className="monkey-preview-action-no">{action.action_no}</span>
                      <div className="monkey-preview-action-detail">
                        <div className="monkey-preview-action-element">{action.element_title}</div>
                        <div className="monkey-preview-action-meta">
                          <span>动作：{actionTypeLabel(action.action_type)}</span>
                          <span>依赖：{action.data_dependency || "无"}</span>
                          <span>状态：{statusLabel(action.status)}</span>
                          {action.center && (
                            <span>
                              坐标：({action.center.x}, {action.center.y})
                            </span>
                          )}
                          {resultTitle && <span>跳转：{resultTitle}</span>}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
