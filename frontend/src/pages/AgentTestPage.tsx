import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { isApiOfflineError } from "../api/http";
import AgentExecutionGallery from "../components/AgentExecutionGallery";
import type {
  AgentLogItem,
  AgentRunState,
  CaseListItem,
  ProviderInfo,
} from "../types/agent";
import "./AgentTestPage.css";

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString();
}

export default function AgentTestPage() {
  const stopStreamRef = useRef<(() => void) | null>(null);
  const intentScrollRef = useRef<HTMLDivElement | null>(null);
  const verifierScrollRef = useRef<HTMLDivElement | null>(null);

  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [run, setRun] = useState<AgentRunState | null>(null);
  const [intentLogs, setIntentLogs] = useState<AgentLogItem[]>([]);
  const [verifierLogs, setVerifierLogs] = useState<AgentLogItem[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentReady, setAgentReady] = useState(true);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");

  const executionAttempts = useMemo(() => run?.attempts ?? [], [run]);

  const activeStepOrder = useMemo(() => {
    if (!run || !["running", "pending"].includes(run.status)) {
      return null;
    }
    const runningStep = run.steps.find((step) => step.status === "running");
    if (runningStep) {
      return runningStep.step_order;
    }
    if (run.current_step_index < run.total_steps) {
      return run.current_step_index;
    }
    return null;
  }, [run]);

  const loadCases = useCallback(async () => {
    setLoadingCases(true);
    setError(null);
    try {
      const list = await agentApi.listCases(10);
      setCases(list);
      setSelectedCaseId((current) => current ?? list[0]?.id ?? null);

      const ready = await agentApi.checkReady();
      setAgentReady(ready);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    } finally {
      setLoadingCases(false);
    }
  }, []);

  const loadProviders = useCallback(async () => {
    try {
      const resp = await agentApi.listProviders();
      // 只保留实测可达的 provider，未配置 / 连不上的直接不展示
      const reachable = resp.providers.filter((item) => item.available);
      setProviders(reachable);
      setSelectedProvider((current) => {
        if (current && reachable.some((p) => p.id === current)) {
          return current;
        }
        if (resp.default && reachable.some((p) => p.id === resp.default)) {
          return resp.default;
        }
        return reachable[0]?.id ?? "";
      });
    } catch (err) {
      if (!isApiOfflineError(err)) {
        console.warn("加载模型列表失败", err);
      }
    }
  }, []);

  useEffect(() => {
    void loadCases();
    void loadProviders();
    return () => stopStreamRef.current?.();
  }, [loadCases, loadProviders]);

  // 终态后清掉所有实时日志（负 ID），只保留持久化结果。
  useEffect(() => {
    if (!run) return;
    if (!["completed", "failed", "cancelled"].includes(run.status)) return;
    setIntentLogs((prev) => prev.filter((item) => item.id >= 0));
    setVerifierLogs((prev) => prev.filter((item) => item.id >= 0));
  }, [run?.status]);

  useEffect(() => {
    const el = intentScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [intentLogs.length]);

  useEffect(() => {
    const el = verifierScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [verifierLogs.length]);

  const mergeLogs = (prev: AgentLogItem[], incoming: AgentLogItem[]) => {
    const map = new Map(prev.map((item) => [item.id, item]));
    incoming.forEach((item) => map.set(item.id, item));
    return Array.from(map.values()).sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
  };

  const appendLogs = (logs: AgentLogItem[]) => {
    if (!logs.length) {
      return;
    }
    setIntentLogs((prev) => mergeLogs(prev, logs.filter((item) => item.agent_type === "intent")));
    setVerifierLogs((prev) => mergeLogs(prev, logs.filter((item) => item.agent_type === "verifier")));
  };

  const handleStart = async () => {
    if (!selectedCaseId || running) {
      return;
    }

    stopStreamRef.current?.();
    setError(null);
    setIntentLogs([]);
    setVerifierLogs([]);
    setRunning(true);

    try {
      const created = await agentApi.startRun(selectedCaseId, selectedProvider || null);
      setRun(created);

      stopStreamRef.current = agentApi.streamRun(created.run_id, {
        onEvent: (event) => {
          if (event.run) {
            setRun(event.run);
          }
          if (event.logs?.length) {
            appendLogs(event.logs);
          }
        },
        onError: (err) => setError(err.message),
        onDone: () => setRunning(false),
      });
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : "启动执行失败");
    }
  };

  const handleCancel = async () => {
    if (!run?.run_id) {
      return;
    }
    stopStreamRef.current?.();
    stopStreamRef.current = null;
    try {
      await agentApi.cancelRun(run.run_id);
      const latest = await agentApi.getRun(run.run_id);
      setRun(latest);
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="agent-test-page">
      <header className="agent-test-toolbar">
        <div className="agent-test-toolbar-left">
          <span className="agent-test-toolbar-title">Agent 测试执行</span>
          {run && (
            <span className="agent-test-run-badge">
              {run.case_name} · {run.status} · 步骤{" "}
              {(activeStepOrder ?? run.current_step_index) + 1}/{run.total_steps}
              {run.llm_provider ? ` · ${run.llm_provider}` : ""}
            </span>
          )}
        </div>
        <div className="agent-test-toolbar-actions">
          <label className="agent-test-provider">
            <span>模型</span>
            <select
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value)}
              disabled={running || providers.length === 0}
              title={
                providers.length === 0
                  ? "未检测到任何可达模型（本地 Ollama / 在线 LLM 均连不上）"
                  : undefined
              }
            >
              {providers.length === 0 && <option value="">无可用模型</option>}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="agent-test-provider-refresh"
              onClick={() => void loadProviders()}
              disabled={running}
              title="重新探测模型可达性"
            >
              ↻
            </button>
          </label>
          <button className="secondary-btn" type="button" onClick={() => void loadCases()} disabled={loadingCases}>
            刷新 Case
          </button>
          <button
            className="primary-btn"
            type="button"
            disabled={!selectedCaseId || running || !agentReady}
            onClick={() => void handleStart()}
          >
            {running ? "执行中..." : "开始执行"}
          </button>
          <button
            className="secondary-btn"
            type="button"
            disabled={!run || !running}
            onClick={() => void handleCancel()}
          >
            取消
          </button>
        </div>
      </header>

      {error && <div className="agent-test-error">{error}</div>}

      <div className="agent-test-grid">
        <section className="agent-panel agent-panel-cases">
          <header className="agent-panel-header">
            <h3>已保存 Case</h3>
            <span>默认显示最近 10 条</span>
          </header>
          <div className="agent-panel-body">
            {loadingCases && <div className="agent-panel-empty">加载中...</div>}
            {!loadingCases && cases.length === 0 && (
              <div className="agent-panel-empty">暂无已保存 Case</div>
            )}
            <ul className="agent-case-list">
              {cases.map((item) => {
                const isSelected = selectedCaseId === item.id;
                const isRunningCase = run?.case_id === item.id;
                return (
                  <li
                    key={item.id}
                    className={isSelected ? "agent-case-block agent-case-block-active" : "agent-case-block"}
                  >
                    <button
                      type="button"
                      className={isSelected ? "agent-case-item agent-case-item-active" : "agent-case-item"}
                      onClick={() => setSelectedCaseId(item.id)}
                    >
                      <strong>{item.name}</strong>
                      <span>
                        #{item.id} · {item.step_count} 步
                      </span>
                    </button>
                    {isSelected && item.steps.length > 0 && (
                      <ol className="agent-case-steps">
                        {item.steps.map((step) => {
                          const runStep = isRunningCase
                            ? run?.steps.find((record) => record.step_order === step.step_order)
                            : null;
                          const isActive = isRunningCase && activeStepOrder === step.step_order;
                          const stepClass = [
                            "agent-case-step",
                            isActive ? "agent-case-step-running" : "",
                            runStep?.status === "success" ? "agent-case-step-success" : "",
                            runStep?.status === "failed" ? "agent-case-step-failed" : "",
                          ]
                            .filter(Boolean)
                            .join(" ");
                          return (
                            <li key={step.step_order} className={stepClass}>
                              <span className="agent-case-step-index">{step.step_order + 1}</span>
                              <span className="agent-case-step-desc">{step.description}</span>
                            </li>
                          );
                        })}
                      </ol>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        <section className="agent-panel agent-panel-logs">
          <header className="agent-panel-header">
            <h3>意图分析 Agent</h3>
            <span>{running ? "执行中 · 实时跟踪" : "执行结果"}</span>
          </header>
          <div className="agent-panel-body agent-log-body" ref={intentScrollRef}>
            {intentLogs.length === 0 && (
              <div className="agent-panel-empty">
                {running ? "等待意图分析 Agent 开始工作..." : "尚无意图分析记录"}
              </div>
            )}
            {intentLogs.map((log) => {
              const isLive = log.id < 0;
              return (
                <article
                  key={log.id}
                  className={isLive ? "agent-log-item agent-log-item-live" : "agent-log-item"}
                >
                  <div className="agent-log-meta">
                    <span>
                      {isLive && <em className="agent-log-live-dot">●</em>}
                      步骤 {(log.step_order ?? 0) + 1}
                    </span>
                    <time>{formatTime(log.created_at)}</time>
                  </div>
                  <p>{log.message}</p>
                  {log.detail && <pre>{JSON.stringify(log.detail, null, 2)}</pre>}
                </article>
              );
            })}
          </div>
        </section>

        <section className="agent-panel agent-panel-logs">
          <header className="agent-panel-header">
            <h3>验证 Agent</h3>
            <span>{running ? "执行中 · 实时跟踪" : "验证结果"}</span>
          </header>
          <div className="agent-panel-body agent-log-body" ref={verifierScrollRef}>
            {verifierLogs.length === 0 && (
              <div className="agent-panel-empty">
                {running ? "等待步骤验证 Agent 开始工作..." : "尚无验证记录"}
              </div>
            )}
            {verifierLogs.map((log) => {
              const isLive = log.id < 0;
              return (
                <article
                  key={log.id}
                  className={isLive ? "agent-log-item agent-log-item-live" : "agent-log-item"}
                >
                  <div className="agent-log-meta">
                    <span>
                      {isLive && <em className="agent-log-live-dot">●</em>}
                      步骤 {(log.step_order ?? 0) + 1}
                    </span>
                    <time>{formatTime(log.created_at)}</time>
                  </div>
                  <p>{log.message}</p>
                  {log.detail && <pre>{JSON.stringify(log.detail, null, 2)}</pre>}
                </article>
              );
            })}
          </div>
        </section>

        <section className="agent-panel agent-panel-images">
          <header className="agent-panel-header">
            <h3>执行截图</h3>
            <span>全程记录 · 点击放大</span>
          </header>
          <div className="agent-panel-body agent-image-body">
            <AgentExecutionGallery attempts={executionAttempts} />
          </div>
        </section>
      </div>
    </section>
  );
}
