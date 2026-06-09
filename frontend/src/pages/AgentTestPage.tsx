import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import type { AgentLogItem, AgentRunState, AgentStepRecord, CaseListItem } from "../types/agent";
import "./AgentTestPage.css";

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString();
}

function pickDisplayStep(run: AgentRunState | null): AgentStepRecord | null {
  if (!run?.steps.length) {
    return null;
  }
  const running = run.steps.find((step) => step.status === "running");
  if (running) {
    return running;
  }
  const withImages = [...run.steps].reverse().find(
    (step) => step.before_image_annotated || step.before_image || step.after_image
  );
  return withImages ?? run.steps[Math.max(0, run.current_step_index - 1)] ?? null;
}

export default function AgentTestPage() {
  const stopStreamRef = useRef<(() => void) | null>(null);

  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [run, setRun] = useState<AgentRunState | null>(null);
  const [intentLogs, setIntentLogs] = useState<AgentLogItem[]>([]);
  const [verifierLogs, setVerifierLogs] = useState<AgentLogItem[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [agentReady, setAgentReady] = useState(true);

  const displayStep = useMemo(() => pickDisplayStep(run), [run]);

  const loadCases = useCallback(async () => {
    setLoadingCases(true);
    setError(null);
    setWarning(null);
    try {
      const list = await agentApi.listCases(10);
      setCases(list);
      setSelectedCaseId((current) => current ?? list[0]?.id ?? null);

      const ready = await agentApi.checkReady();
      setAgentReady(ready);
      if (!ready) {
        setWarning("Agent 执行接口未就绪，Case 列表已加载。请关闭旧的后端窗口后重新运行 start.bat，再点击「开始执行」。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Case 列表失败");
    } finally {
      setLoadingCases(false);
    }
  }, []);

  useEffect(() => {
    void loadCases();
    return () => stopStreamRef.current?.();
  }, [loadCases]);

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
      const created = await agentApi.startRun(selectedCaseId);
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
              {run.case_name} · {run.status} · 步骤 {run.current_step_index}/{run.total_steps}
            </span>
          )}
        </div>
        <div className="agent-test-toolbar-actions">
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

      {warning && <div className="agent-test-warning">{warning}</div>}
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
              {cases.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={
                      selectedCaseId === item.id
                        ? "agent-case-item agent-case-item-active"
                        : "agent-case-item"
                    }
                    onClick={() => setSelectedCaseId(item.id)}
                  >
                    <strong>{item.name}</strong>
                    <span>
                      #{item.id} · {item.step_count} 步
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="agent-panel agent-panel-logs">
          <header className="agent-panel-header">
            <h3>意图分析 Agent</h3>
            <span>实时分析日志</span>
          </header>
          <div className="agent-panel-body agent-log-body">
            {intentLogs.length === 0 && <div className="agent-panel-empty">等待意图分析...</div>}
            {intentLogs.map((log) => (
              <article key={log.id} className="agent-log-item">
                <div className="agent-log-meta">
                  <span>步骤 {(log.step_order ?? 0) + 1}</span>
                  <time>{formatTime(log.created_at)}</time>
                </div>
                <p>{log.message}</p>
                {log.detail && (
                  <pre>{JSON.stringify(log.detail, null, 2)}</pre>
                )}
              </article>
            ))}
          </div>
        </section>

        <section className="agent-panel agent-panel-logs">
          <header className="agent-panel-header">
            <h3>验证 Agent</h3>
            <span>实时验证日志</span>
          </header>
          <div className="agent-panel-body agent-log-body">
            {verifierLogs.length === 0 && <div className="agent-panel-empty">等待步骤验证...</div>}
            {verifierLogs.map((log) => (
              <article key={log.id} className="agent-log-item">
                <div className="agent-log-meta">
                  <span>步骤 {(log.step_order ?? 0) + 1}</span>
                  <time>{formatTime(log.created_at)}</time>
                </div>
                <p>{log.message}</p>
                {log.detail && (
                  <pre>{JSON.stringify(log.detail, null, 2)}</pre>
                )}
              </article>
            ))}
          </div>
        </section>

        <section className="agent-panel agent-panel-images">
          <header className="agent-panel-header">
            <h3>执行截图</h3>
            <span>执行前标注 / 执行后对比</span>
          </header>
          <div className="agent-panel-body agent-image-body">
            {!displayStep && <div className="agent-panel-empty">执行后将显示截图</div>}
            {displayStep && (
              <div className="agent-image-grid">
                <figure className="agent-image-card">
                  <figcaption>执行前（含操作标注）</figcaption>
                  {displayStep.before_image_annotated || displayStep.before_image ? (
                    <img
                      src={displayStep.before_image_annotated || displayStep.before_image || ""}
                      alt="执行前截图"
                    />
                  ) : (
                    <div className="agent-image-placeholder">暂无</div>
                  )}
                </figure>
                <figure className="agent-image-card">
                  <figcaption>执行后</figcaption>
                  {displayStep.after_image ? (
                    <img src={displayStep.after_image} alt="执行后截图" />
                  ) : (
                    <div className="agent-image-placeholder">暂无</div>
                  )}
                </figure>
              </div>
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
