import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { isApiOfflineError } from "../api/http";
import { monkeyApi } from "../api/monkey";
import DeviceScreen from "../components/DeviceScreen";
import MonkeyExploreTree from "../components/MonkeyExploreTree";
import MonkeyTreeGraph from "../components/MonkeyTreeGraph";
import type { DeviceInfo } from "../types";
import type { MonkeyLogItem, MonkeyNode, MonkeyProviderInfo, MonkeySession } from "../types/monkey";
import "./AgentMonkeyTestPage.css";

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString();
}

function mergeNodes(existing: MonkeyNode[], incoming: MonkeyNode[]): MonkeyNode[] {
  const map = new Map(existing.map((node) => [node.node_uuid, node]));
  for (const node of incoming) {
    map.set(node.node_uuid, node);
  }
  return Array.from(map.values()).sort((a, b) => a.depth - b.depth || a.title.localeCompare(b.title, "zh-CN"));
}

export default function AgentMonkeyTestPage() {
  const stopStreamRef = useRef<(() => void) | null>(null);

  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(true);

  const [providers, setProviders] = useState<MonkeyProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [targetAppName, setTargetAppName] = useState("");
  const [session, setSession] = useState<MonkeySession | null>(null);
  const [nodes, setNodes] = useState<MonkeyNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<MonkeyNode | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [graphRootUuid, setGraphRootUuid] = useState<string | null>(null);
  const [logs, setLogs] = useState<MonkeyLogItem[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rootNode = useMemo(() => nodes.find((node) => node.node_type === "root") ?? null, [nodes]);

  const refreshDevices = useCallback(async () => {
    try {
      const list = await api.listDevices();
      setDevices(list);
      if (list.length > 0) {
        const nextSerial = selectedSerial && list.some((d) => d.serial === selectedSerial) ? selectedSerial : list[0].serial;
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

  const reloadTree = useCallback(async (sessionUuid: string) => {
    const tree = await monkeyApi.getTree(sessionUuid);
    setNodes(tree.nodes);
  }, []);

  useEffect(() => {
    void refreshDevices();
    void loadProviders();
    return () => stopStreamRef.current?.();
  }, [refreshDevices, loadProviders]);

  const handleSelectDevice = async (serial: string) => {
    setSelectedSerial(serial);
    await api.selectDevice(serial);
  };

  const handleStart = async () => {
    if (running || !targetAppName.trim()) {
      return;
    }
    setError(null);
    setLogs([]);
    setNodes([]);
    setSelectedNode(null);
    setShowGraph(false);
    setGraphRootUuid(null);

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
          if (event.session) {
            setSession(event.session);
          }
          if (event.nodes && event.nodes.length > 0) {
            setNodes((current) => mergeNodes(current, event.nodes ?? []));
          }
          if (event.logs && event.logs.length > 0) {
            setLogs((current) => [...current, ...event.logs!]);
          }
          if (event.type === "tree_update" || event.type === "step") {
            void reloadTree(created.session_uuid).catch(() => undefined);
          }
        },
        onError: (err) => {
          setError(err.message);
          setRunning(false);
        },
        onDone: () => {
          setRunning(false);
          void reloadTree(created.session_uuid).catch(() => undefined);
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
      const updated = await monkeyApi.getSession(session.session_uuid);
      setSession(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败");
    }
  };

  const handleSelectNode = (node: MonkeyNode) => {
    setSelectedNode(node);
    setShowGraph(false);
  };

  const handleSelectRoot = (node: MonkeyNode) => {
    setGraphRootUuid(node.node_uuid);
    setShowGraph(true);
  };

  const previewUrl = selectedNode?.annotated_screenshot_url ?? selectedNode?.screenshot_url ?? null;

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
            <button className="primary-btn" type="button" disabled={running || !targetAppName.trim()} onClick={() => void handleStart()}>
              开始探索
            </button>
            <button className="secondary-btn" type="button" disabled={!running || !session} onClick={() => void handleStop()}>
              停止
            </button>
          </div>
        </div>

        {session && (
          <div className={`monkey-status ${session.status}`}>
            会话 {session.session_uuid.slice(0, 8)} · 状态 {session.status} · 步骤 {session.step_count}/{session.max_steps}
            {session.error ? ` · ${session.error}` : ""}
          </div>
        )}
        {error && <div className="monkey-error">{error}</div>}

        <div className="monkey-main">
          <div className="monkey-tree-panel">
            <div className="monkey-panel-header">
              <h3>探索树</h3>
              {rootNode && (
                <button type="button" className="secondary-btn" onClick={() => handleSelectRoot(rootNode)}>
                  查看结构图
                </button>
              )}
            </div>
            <div className="monkey-panel-body">
              {showGraph && graphRootUuid ? (
                <MonkeyTreeGraph
                  nodes={nodes}
                  rootUuid={graphRootUuid}
                  selectedNodeUuid={selectedNode?.node_uuid ?? null}
                  onSelectNode={handleSelectNode}
                />
              ) : (
                <MonkeyExploreTree
                  nodes={nodes}
                  selectedNodeUuid={selectedNode?.node_uuid ?? null}
                  onSelectNode={handleSelectNode}
                  onSelectRoot={handleSelectRoot}
                />
              )}
            </div>
          </div>

          <div className="monkey-detail-panel">
            <div className="monkey-panel-header">
              <h3>{selectedNode ? selectedNode.title : "节点详情 / 日志"}</h3>
            </div>
            <div className="monkey-panel-body">
              {selectedNode ? (
                <div className="monkey-detail-grid">
                  {previewUrl ? (
                    <img className="monkey-shot" src={previewUrl} alt={selectedNode.title} />
                  ) : (
                    <div className="monkey-tree-empty">无截图</div>
                  )}
                  <div className="monkey-meta">
                    <div>类型：{selectedNode.node_type}</div>
                    <div>状态：{selectedNode.status}</div>
                    <div>深度：{selectedNode.depth}</div>
                    {selectedNode.center && (
                      <div>
                        坐标：({selectedNode.center.x}, {selectedNode.center.y})
                      </div>
                    )}
                    {selectedNode.description && <div>说明：{selectedNode.description}</div>}
                  </div>
                </div>
              ) : (
                <div className="monkey-logs">
                  {logs.length === 0 ? (
                    <div className="monkey-tree-empty">探索日志将在此显示</div>
                  ) : (
                    logs.map((log) => (
                      <div key={`${log.id}-${log.created_at}`} className={`monkey-log-item ${log.id < 0 ? "live" : ""}`}>
                        [{formatTime(log.created_at)}] {log.message}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
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
          highlightCenter={selectedNode?.center ?? null}
          highlightBBox={selectedNode?.bbox ?? null}
        />
      </section>
    </main>
  );
}
