import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { batchApi } from "../api/platform";
import { agentApi } from "../api/agent";
import { isApiOfflineError } from "../api/http";
import type { CaseListItem, ProviderInfo } from "../types/agent";
import "./PlatformPages.css";

export default function BatchPage() {
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [execMode, setExecMode] = useState<"position" | "code" | "dual">("position");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [enableVerifier, setEnableVerifier] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void agentApi.listCases(100).then(setCases).catch(() => undefined);
    void agentApi.listProviders().then((resp) => {
      const reachable = resp.providers.filter((p) => p.available);
      setProviders(reachable);
      setSelectedProvider(reachable[0]?.id ?? "");
    });
  }, []);

  const toggleCase = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleStart = useCallback(async () => {
    if (selectedIds.size === 0 || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const resp = await batchApi.start({
        case_ids: [...selectedIds],
        exec_mode: execMode,
        llm_provider: selectedProvider || undefined,
        enable_verifier: enableVerifier,
      });
      setResult(
        `批量任务已启动 · 模式=${resp.exec_mode} · 任务=${resp.task_uuid ?? "—"} · Position=${(resp.position_batch as { batch_id?: string } | null)?.batch_id ?? "—"} · Code=${(resp.code_batch as { batch_id?: string } | null)?.batch_id ?? "—"}`
      );
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "启动失败");
      }
    } finally {
      setRunning(false);
    }
  }, [selectedIds, running, execMode, selectedProvider, enableVerifier]);

  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>跑批管理</h2>
        <div className="platform-toolbar">
          <select className="platform-select" value={execMode} onChange={(e) => setExecMode(e.target.value as typeof execMode)}>
            <option value="position">Position</option>
            <option value="code">Code</option>
            <option value="dual">Dual（双路径）</option>
          </select>
          <select className="platform-select" value={selectedProvider} onChange={(e) => setSelectedProvider(e.target.value)}>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <label style={{ color: "#9ca3af", fontSize: "0.875rem" }}>
            <input type="checkbox" checked={enableVerifier} onChange={(e) => setEnableVerifier(e.target.checked)} /> 启用验证器
          </label>
          <button className="platform-btn platform-btn-primary" type="button" disabled={running || selectedIds.size === 0} onClick={() => void handleStart()}>
            {running ? "启动中…" : `启动批量 (${selectedIds.size})`}
          </button>
          <Link className="platform-btn" to="/tasks">
            任务中心
          </Link>
          <Link className="platform-btn" to="/reports">
            报告中心
          </Link>
        </div>
      </div>

      {error && <div className="platform-error">{error}</div>}
      {result && <div className="platform-card"><p>{result}</p></div>}

      <div className="platform-table-wrap">
        <table className="platform-table">
          <thead>
            <tr>
              <th></th>
              <th>ID</th>
              <th>名称</th>
              <th>步骤数</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id}>
                <td>
                  <input type="checkbox" checked={selectedIds.has(c.id)} onChange={() => toggleCase(c.id)} />
                </td>
                <td>{c.id}</td>
                <td>{c.name}</td>
                <td>{c.step_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
