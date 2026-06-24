import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { isApiOfflineError } from "../api/http";
import { monkeyApi } from "../api/monkey";
import DeviceScreen from "../components/DeviceScreen";
import MonkeyScreenPreviewModal from "../components/MonkeyScreenPreviewModal";
import MonkeyScreenTreeGallery from "../components/MonkeyScreenTreeGallery";
import type { DeviceInfo } from "../types";
import type {
  MonkeyLogItem,
  MonkeyNode,
  MonkeyProviderInfo,
  MonkeyScreenAction,
  MonkeySession,
} from "../types/monkey";
import "./AgentMonkeyTestPage.css";

type CollapseKey = "detail" | "ledger" | "logs";

const GALLERY_ZOOM_MIN = 0.5;
const GALLERY_ZOOM_MAX = 2;
const GALLERY_ZOOM_STEP = 0.1;

function clampZoom(value: number) {
  return Math.min(GALLERY_ZOOM_MAX, Math.max(GALLERY_ZOOM_MIN, Math.round(value * 10) / 10));
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString();
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

function logTypeLabel(logType: string) {
  if (logType === "model") return "模型";
  if (logType === "nav") return "导航";
  if (logType === "action") return "操作";
  if (logType === "screen") return "屏幕";
  return "系统";
}

function mergeLogs(current: MonkeyLogItem[], incoming: MonkeyLogItem[]) {
  const merged = [...current];
  for (const log of incoming) {
    if (!merged.some((item) => item.id === log.id)) {
      merged.push(log);
    }
  }
  merged.sort((a, b) => a.id - b.id);
  return merged;
}

export default function AgentMonkeyTestPage() {
  const stopStreamRef = useRef<(() => void) | null>(null);
  const lastLogIdRef = useRef(0);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(true);

  const [providers, setProviders] = useState<MonkeyProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [targetAppName, setTargetAppName] = useState("");
  const [session, setSession] = useState<MonkeySession | null>(null);
  const [screens, setScreens] = useState<MonkeyNode[]>([]);
  const [treeNodes, setTreeNodes] = useState<MonkeyNode[]>([]);
  const [actions, setActions] = useState<MonkeyScreenAction[]>([]);
  const [selectedScreenUuid, setSelectedScreenUuid] = useState<string | null>(null);
  const [logs, setLogs] = useState<MonkeyLogItem[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<CollapseKey>>(new Set());
  const [galleryZoom, setGalleryZoom] = useState(1);
  const [previewScreen, setPreviewScreen] = useState<MonkeyNode | null>(null);
  const galleryScrollRef = useRef<HTMLDivElement>(null);

  const selectedScreen = useMemo(() => {
    const found = screens.find((s) => s.node_uuid === selectedScreenUuid);
    if (found && found.node_type !== "root") return found;
    return screens.filter((s) => s.node_type !== "root").slice(-1)[0] ?? null;
  }, [screens, selectedScreenUuid]);

  const screenActions = useMemo(() => {
    if (!selectedScreen) return [];
    return actions
      .filter((a) => a.screen_node_uuid === selectedScreen.node_uuid)
      .sort((a, b) => a.action_no - b.action_no);
  }, [actions, selectedScreen]);

  const previewUrl = selectedScreen
    ? (() => {
        const raw = selectedScreen.annotated_screenshot_url ?? selectedScreen.screenshot_url ?? null;
        if (!raw) return null;
        const sep = raw.includes("?") ? "&" : "?";
        return `${raw}${sep}t=${encodeURIComponent(selectedScreen.updated_at)}`;
      })()
    : null;

  const togglePanel = (key: CollapseKey) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const refreshDevices = useCallback(async () => {
    try {
      const list = await api.listDevices();
      setDevices(list);
      if (list.length > 0) {
        const nextSerial =
          selectedSerial && list.some((d) => d.serial === selectedSerial) ? selectedSerial : list[0].serial;
        setSelectedSerial(nextSerial);
        await api.selectDevice(nextSerial);
      }
    } catch {
      // 静默
    } finally {
      setDeviceLoading(false);
    }
  }, [selectedSerial]);

  const loadProviders = useCallback(async () => {
    try {
      const resp = await monkeyApi.listProviders();
      const reachable = resp.providers.filter((item) => item.available);
      setProviders(reachable);
      setSelectedProvider((current) => {
        if (current && reachable.some((p) => p.id === current)) return current;
        if (resp.default && reachable.some((p) => p.id === resp.default)) return resp.default;
        return reachable[0]?.id ?? "";
      });
    } catch (err) {
      if (!isApiOfflineError(err)) {
        console.warn("加载模型列表失败", err);
      }
    }
  }, []);

  const applyExploreState = useCallback(
    (state: {
      session: MonkeySession;
      screens: MonkeyNode[];
      tree_nodes: MonkeyNode[];
      actions: MonkeyScreenAction[];
      logs: MonkeyLogItem[];
    }) => {
      setSession(state.session);
      setScreens(state.screens);
      setTreeNodes(state.tree_nodes?.length ? state.tree_nodes : state.screens);
      setActions(state.actions);
      setLogs(state.logs);
      lastLogIdRef.current = state.logs.reduce((max, log) => Math.max(max, log.id), 0);
      setSelectedScreenUuid((current) => {
        const focus = state.session.focus_screen_uuid ?? state.session.current_node_uuid;
        if (current && state.screens.some((s) => s.node_uuid === current)) return current;
        if (focus && state.screens.some((s) => s.node_uuid === focus)) {
          return focus;
        }
        return state.screens.filter((s) => s.node_type !== "root").slice(-1)[0]?.node_uuid ?? null;
      });
    },
    []
  );

  const reloadState = useCallback(
    async (sessionUuid: string) => {
      const state = await monkeyApi.getExploreState(sessionUuid);
      applyExploreState(state);
    },
    [applyExploreState]
  );

  useEffect(() => {
    void refreshDevices();
    void loadProviders();
    return () => stopStreamRef.current?.();
  }, [refreshDevices, loadProviders]);

  useEffect(() => {
    if (!running || !session) return;
    const timer = window.setInterval(() => {
      void monkeyApi
        .getLogsSince(session.session_uuid, lastLogIdRef.current)
        .then((resp) => {
          if (resp.logs.length > 0) {
            lastLogIdRef.current = resp.latest_id;
            setLogs((current) => mergeLogs(current, resp.logs));
          }
        })
        .catch(() => undefined);
      void reloadState(session.session_uuid).catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [running, session, reloadState]);

  useEffect(() => {
    if (!running || !expanded.has("logs")) return;
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs, running, expanded]);

  const handleSelectDevice = async (serial: string) => {
    setSelectedSerial(serial);
    await api.selectDevice(serial);
  };

  const handleSelectScreen = (node: MonkeyNode) => {
    if (node.node_type === "root") return;
    setSelectedScreenUuid(node.node_uuid);
  };

  const handlePreviewScreen = (node: MonkeyNode) => {
    if (node.node_type === "root") return;
    setSelectedScreenUuid(node.node_uuid);
    setPreviewScreen(node);
  };

  const handleGalleryWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setGalleryZoom((current) => clampZoom(current + (event.deltaY < 0 ? GALLERY_ZOOM_STEP : -GALLERY_ZOOM_STEP)));
  };

  const handleStart = async () => {
    if (running || !targetAppName.trim()) return;
    setError(null);
    setLogs([]);
    lastLogIdRef.current = 0;
    setScreens([]);
    setTreeNodes([]);
    setActions([]);
    setSelectedScreenUuid(null);
    setExpanded(new Set(["logs"]));

    try {
      const created = await monkeyApi.createSession({
        target_app_name: targetAppName.trim(),
        serial: selectedSerial,
        llm_provider: selectedProvider || null,
      });
      setSession(created);
      setRunning(true);

      stopStreamRef.current?.();
      stopStreamRef.current = monkeyApi.streamExplore(created.session_uuid, {
        onEvent: (event) => {
          if (event.session) setSession(event.session);
          if (event.screens && event.screens.length > 0) setScreens(event.screens);
          if (event.nodes && event.nodes.length > 0) setTreeNodes(event.nodes);
          if (event.actions) setActions(event.actions);
          if (event.logs && event.logs.length > 0) {
            setLogs((current) => {
              const merged = mergeLogs(current, event.logs!);
              lastLogIdRef.current = merged.reduce((max, log) => Math.max(max, log.id), 0);
              return merged;
            });
          }
          if (event.session?.focus_screen_uuid ?? event.session?.current_node_uuid) {
            setSelectedScreenUuid(event.session.focus_screen_uuid ?? event.session.current_node_uuid ?? null);
          }
          if (
            event.type === "bootstrap" ||
            event.type === "step" ||
            event.type === "progress" ||
            event.type === "start"
          ) {
            void reloadState(created.session_uuid).catch(() => undefined);
          }
        },
        onError: (err) => {
          setError(err.message);
          setRunning(false);
        },
        onDone: () => {
          setRunning(false);
          void reloadState(created.session_uuid).catch(() => undefined);
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动探索失败");
      setRunning(false);
    }
  };

  const handleStop = async () => {
    if (!session) return;
    try {
      await monkeyApi.stopSession(session.session_uuid);
      stopStreamRef.current?.();
      stopStreamRef.current = null;
      setRunning(false);
      await reloadState(session.session_uuid);
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败");
    }
  };

  return (
    <main className="monkey-workspace">
      <section className="monkey-left">
        <div className="monkey-toolbar">
          <div className="monkey-field">
            <label htmlFor="monkey-target-app">目标应用</label>
            <input
              id="monkey-target-app"
              value={targetAppName}
              onChange={(event) => setTargetAppName(event.target.value)}
              placeholder="例如：微信"
              disabled={running}
            />
          </div>
          <div className="monkey-field">
            <label htmlFor="monkey-provider">模型</label>
            <select
              id="monkey-provider"
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value)}
              disabled={running || providers.length === 0}
            >
              {providers.length === 0 ? (
                <option value="">无可用模型</option>
              ) : (
                providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label} · {provider.model}
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="monkey-actions">
            <button
              className="primary-btn"
              type="button"
              disabled={running || !targetAppName.trim()}
              onClick={() => void handleStart()}
            >
              开始探索
            </button>
            <button className="secondary-btn" type="button" disabled={!running || !session} onClick={() => void handleStop()}>
              停止
            </button>
          </div>
        </div>

        {session && (
          <div className={`monkey-status ${session.status}`}>
            会话 {session.session_uuid.slice(0, 8)} · 状态 {session.status} · 步骤{" "}
            {session.max_steps > 0
              ? `${session.step_count}/${session.max_steps}`
              : session.step_count}
            · 屏幕 {screens.filter((s) => s.node_type !== "root").length} · 操作 {actions.length}
            {session.error ? ` · ${session.error}` : ""}
          </div>
        )}
        {error && <div className="monkey-error">{error}</div>}

        <div className="monkey-gallery-section fill">
          <div className="monkey-panel-header">
            <h3>探索树 · 屏幕画廊</h3>
            <div className="monkey-gallery-tools">
              <span className="monkey-hint">Ctrl+滚轮缩放</span>
              <div className="monkey-zoom-controls">
                <button
                  type="button"
                  className="secondary-btn monkey-zoom-btn"
                  onClick={() => setGalleryZoom((z) => clampZoom(z - GALLERY_ZOOM_STEP))}
                  disabled={galleryZoom <= GALLERY_ZOOM_MIN}
                  aria-label="缩小"
                >
                  −
                </button>
                <span className="monkey-zoom-label">{Math.round(galleryZoom * 100)}%</span>
                <button
                  type="button"
                  className="secondary-btn monkey-zoom-btn"
                  onClick={() => setGalleryZoom((z) => clampZoom(z + GALLERY_ZOOM_STEP))}
                  disabled={galleryZoom >= GALLERY_ZOOM_MAX}
                  aria-label="放大"
                >
                  +
                </button>
                <button
                  type="button"
                  className="secondary-btn monkey-zoom-btn"
                  onClick={() => setGalleryZoom(1)}
                  disabled={galleryZoom === 1}
                >
                  重置
                </button>
              </div>
            </div>
          </div>
          <div
            className="monkey-screen-tree-scroll"
            ref={galleryScrollRef}
            onWheel={handleGalleryWheel}
          >
            <MonkeyScreenTreeGallery
              treeNodes={treeNodes}
              actions={actions}
              selectedScreenUuid={selectedScreenUuid}
              focusScreenUuid={session?.focus_screen_uuid ?? session?.current_node_uuid ?? null}
              zoom={galleryZoom}
              onSelectScreen={handleSelectScreen}
              onPreviewScreen={handlePreviewScreen}
            />
          </div>
        </div>

        {previewScreen && (
          <MonkeyScreenPreviewModal
            screen={previewScreen}
            actions={actions}
            screens={screens}
            onClose={() => setPreviewScreen(null)}
          />
        )}

        <div className="monkey-collapse-bar">
          <button
            type="button"
            className={`monkey-collapse-toggle ${expanded.has("detail") ? "open" : ""}`}
            onClick={() => togglePanel("detail")}
          >
            {expanded.has("detail") ? "▾" : "▸"} 屏幕详情
            {selectedScreen ? ` · ${selectedScreen.title}` : ""}
          </button>
          {expanded.has("detail") && (
            <div className="monkey-collapse-body">
              {previewUrl ? (
                <img className="monkey-hero-shot" src={previewUrl} alt={selectedScreen?.title ?? "屏幕"} />
              ) : (
                <div className="monkey-tree-empty">在树上点击屏幕节点查看标注大图</div>
              )}
            </div>
          )}
        </div>

        <div className="monkey-collapse-bar">
          <button
            type="button"
            className={`monkey-collapse-toggle ${expanded.has("ledger") ? "open" : ""}`}
            onClick={() => togglePanel("ledger")}
          >
            {expanded.has("ledger") ? "▾" : "▸"} 操作账本
            {selectedScreen ? ` · ${screenActions.length} 条` : ""}
          </button>
          {expanded.has("ledger") && (
            <div className="monkey-collapse-body">
              {screenActions.length === 0 ? (
                <div className="monkey-tree-empty">该屏幕暂无编号操作</div>
              ) : (
                <table className="monkey-ledger-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>元素</th>
                      <th>动作</th>
                      <th>数据依赖</th>
                      <th>状态</th>
                      <th>结果屏幕</th>
                    </tr>
                  </thead>
                  <tbody>
                    {screenActions.map((action) => (
                      <tr key={action.action_uuid} className={`status-${action.status}`}>
                        <td>{action.action_no}</td>
                        <td>{action.element_title}</td>
                        <td>{actionTypeLabel(action.action_type)}</td>
                        <td>{action.data_dependency || "无"}</td>
                        <td>{statusLabel(action.status)}</td>
                        <td>
                          {action.result_screen_uuid
                            ? screens.find((s) => s.node_uuid === action.result_screen_uuid)?.title ?? "已跳转"
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

        <div className="monkey-collapse-bar">
          <button
            type="button"
            className={`monkey-collapse-toggle ${expanded.has("logs") ? "open" : ""}`}
            onClick={() => togglePanel("logs")}
          >
            {expanded.has("logs") ? "▾" : "▸"} 探索日志
            {logs.length > 0 ? ` · ${logs.length} 条` : ""}
            {running ? " · 实时更新中" : ""}
          </button>
          {expanded.has("logs") && (
            <div className="monkey-collapse-body monkey-logs">
              {logs.length === 0 ? (
                <div className="monkey-tree-empty">日志将在此显示</div>
              ) : (
                <>
                  {logs.slice(-80).map((log) => (
                    <div
                      key={log.id}
                      className={`monkey-log-item log-type-${log.log_type} ${running ? "live" : ""}`}
                    >
                      <span className="monkey-log-time">[{formatTime(log.created_at)}]</span>
                      <span className={`monkey-log-badge type-${log.log_type}`}>
                        {logTypeLabel(log.log_type)}
                      </span>
                      <span className="monkey-log-message">{log.message}</span>
                    </div>
                  ))}
                  <div ref={logsEndRef} />
                </>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="monkey-right">
        <DeviceScreen
          devices={devices}
          selectedSerial={selectedSerial}
          deviceLoading={deviceLoading}
          onRefreshDevices={refreshDevices}
          onSelectDevice={handleSelectDevice}
          onPermissionPresetAdded={() => undefined}
          readOnly={running}
          highlightCenter={null}
          highlightBBox={null}
        />
      </section>
    </main>
  );
}
