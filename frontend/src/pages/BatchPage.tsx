import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { batchApi } from "../api/platform";
import { agentApi } from "../api/agent";
import { isApiOfflineError } from "../api/http";
import type { CaseListItem, ProviderInfo } from "../types/agent";
import OpsPageShell from "../components/OpsPageShell";
import "./PlatformPages.css";

const MODE_OPTIONS = [
  {
    value: "position" as const,
    title: "Position",
    desc: "视觉坐标路径，适合标注与回放对照",
  },
  {
    value: "code" as const,
    title: "Code",
    desc: "uiautomator2 选择器路径，适合稳定回归",
  },
  {
    value: "dual" as const,
    title: "Dual",
    desc: "双路径并行跑批，便于一致性对比",
  },
];

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
  const [q, setQ] = useState("");

  useEffect(() => {
    void agentApi.listCases(100).then(setCases).catch(() => undefined);
    void agentApi.listProviders().then((resp) => {
      const reachable = resp.providers.filter((p) => p.available);
      setProviders(reachable);
      setSelectedProvider(reachable[0]?.id ?? "");
    });
  }, []);

  const filtered = useMemo(() => {
    const key = q.trim().toLowerCase();
    if (!key) return cases;
    return cases.filter((c) => c.name.toLowerCase().includes(key) || String(c.id).includes(key));
  }, [cases, q]);

  const toggleCase = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllFiltered = () => {
    setSelectedIds(new Set(filtered.map((c) => c.id)));
  };

  const clearSelection = () => setSelectedIds(new Set());

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
        `批量任务已启动 · mode=${resp.exec_mode} · task=${resp.task_uuid ?? "—"} · pos=${(resp.position_batch as { batch_id?: string } | null)?.batch_id ?? "—"} · code=${(resp.code_batch as { batch_id?: string } | null)?.batch_id ?? "—"}`
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
    <OpsPageShell
      kicker="Ops · Batch Launch"
      title="跑批管理"
      lead="勾选多个 Case，选择执行模式与模型后一键启动。任务会进入任务中心，结果可在报告中心复盘。"
      stats={[
        { label: "可选 Case", value: cases.length },
        { label: "已选", value: selectedIds.size, tone: "accent" as const },
        { label: "模式", value: execMode, tone: execMode === "code" ? "code" : execMode === "position" ? "pos" : "info" },
      ]}
      actions={
        <>
          <Link className="platform-btn" to="/tasks">
            任务中心
          </Link>
          <Link className="platform-btn" to="/reports">
            报告中心
          </Link>
        </>
      }
    >
      {error && <div className="platform-error">{error}</div>}
      {result && <div className="batch-result-banner">{result}</div>}

      <div className="batch-layout">
        <aside className="batch-config">
          <h3>启动配置</h3>
          <p className="batch-config-hint">先定模式与模型，再勾选 Case。Dual 会同时拉起 Position 与 Code 批次。</p>

          <div className="batch-field">
            <label>执行模式</label>
            <div className="batch-mode-grid">
              {MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`batch-mode-option ${execMode === opt.value ? "active" : ""}`}
                  onClick={() => setExecMode(opt.value)}
                >
                  <div>
                    <strong>{opt.title}</strong>
                    <span>{opt.desc}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="batch-field">
            <label>模型</label>
            <select
              className="platform-select"
              style={{ width: "100%" }}
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
            >
              {providers.length === 0 && <option value="">无可用模型</option>}
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          <label className="batch-check">
            <input
              type="checkbox"
              checked={enableVerifier}
              onChange={(e) => setEnableVerifier(e.target.checked)}
            />
            启用步骤验证器
          </label>

          <button
            className="platform-btn platform-btn-primary"
            type="button"
            style={{ width: "100%", justifyContent: "center" }}
            disabled={running || selectedIds.size === 0}
            onClick={() => void handleStart()}
          >
            {running ? "启动中…" : `启动批量 · ${selectedIds.size} Case`}
          </button>
        </aside>

        <section className="batch-case-panel">
          <div className="batch-case-panel-head">
            <h3>选择 Case</h3>
            <div className="platform-toolbar">
              <input
                className="platform-input"
                placeholder="筛选名称 / ID"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <button className="platform-btn" type="button" onClick={selectAllFiltered}>
                全选
              </button>
              <button className="platform-btn" type="button" onClick={clearSelection}>
                清空
              </button>
            </div>
          </div>
          {filtered.map((c) => {
            const selected = selectedIds.has(c.id);
            return (
              <div
                key={c.id}
                className={`batch-case-row ${selected ? "selected" : ""}`}
                onClick={() => toggleCase(c.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") toggleCase(c.id);
                }}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleCase(c.id)}
                  onClick={(e) => e.stopPropagation()}
                />
                <div>
                  <div className="batch-case-name">{c.name}</div>
                  <div className="batch-case-meta">
                    #{c.id} · {c.step_count} 步
                  </div>
                </div>
                <span className="ops-chip muted">{selected ? "已选" : "可选"}</span>
              </div>
            );
          })}
          {filtered.length === 0 && (
            <div className="platform-empty">没有匹配的 Case</div>
          )}
        </section>
      </div>
    </OpsPageShell>
  );
}
