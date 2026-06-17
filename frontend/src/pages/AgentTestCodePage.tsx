import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentCodeApi } from "../api/agentCode";
import { isApiOfflineError } from "../api/http";
import AgentExecutionGallery from "../components/AgentExecutionGallery";
import type { CaseListItem, ProviderInfo } from "../types/agent";
import type { CodeRunState } from "../types/agentCode";
import { codeRunToGalleryRun } from "../types/agentCode";
import "./AgentTestPage.css";

export default function AgentTestCodePage() {
  const stopStreamRef = useRef<(() => void) | null>(null);
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [run, setRun] = useState<CodeRunState | null>(null);
  const [loadingCases, setLoadingCases] = useState(false);
  const [running, setRunning] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [aborting, setAborting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentReady, setAgentReady] = useState(true);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [enableVerifier, setEnableVerifier] = useState(false);

  const galleryRun = useMemo(() => (run ? codeRunToGalleryRun(run) : null), [run]);

  const activeStepOrder = useMemo(() => {
    if (!run) return null;
    if (["running", "pending"].includes(run.status)) {
      const runningStep = run.steps.find((s) => s.status === "running");
      if (runningStep) return runningStep.step_order;
      if (run.current_step_index < run.total_steps) return run.current_step_index;
    }
    const withCode = [...run.steps].reverse().find((s) => s.generated_code);
    if (withCode) return withCode.step_order;
    return run.current_step_index > 0 ? run.current_step_index - 1 : 0;
  }, [run]);

  const focusStep = useMemo(() => {
    if (!run) return null;
    if (activeStepOrder != null) {
      return run.steps.find((s) => s.step_order === activeStepOrder) ?? null;
    }
    return run.steps.find((s) => s.generated_code) ?? null;
  }, [run, activeStepOrder]);

  const historySteps = useMemo(() => {
    if (!run) return [];
    return run.steps.filter((s) => s.generated_code || s.error).sort((a, b) => a.step_order - b.step_order);
  }, [run]);

  const outputStep = useMemo(() => {
    if (focusStep?.generated_code?.execution_output || focusStep?.error) return focusStep;
    for (let i = historySteps.length - 1; i >= 0; i -= 1) {
      if (historySteps[i].generated_code?.execution_output || historySteps[i].error) {
        return historySteps[i];
      }
    }
    return null;
  }, [focusStep, historySteps]);

  const loadCases = useCallback(async () => {
    setLoadingCases(true);
    setError(null);
    try {
      const list = await agentCodeApi.listCases(10);
      setCases(list);
      setSelectedCaseId((c) => c ?? list[0]?.id ?? null);
      setAgentReady(await agentCodeApi.checkReady());
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
      const resp = await agentCodeApi.listProviders();
      const reachable = resp.providers.filter((p) => p.available);
      setProviders(reachable);
      setSelectedProvider((cur) => {
        if (cur && reachable.some((p) => p.id === cur)) return cur;
        if (resp.default && reachable.some((p) => p.id === resp.default)) return resp.default!;
        return reachable[0]?.id ?? "";
      });
    } catch (err) {
      if (!isApiOfflineError(err)) console.warn(err);
    }
  }, []);

  const handleDeleteCase = async (caseItem: CaseListItem) => {
    if (running || batchRunning) return;
    if (!window.confirm(`确定删除 Case「${caseItem.name}」？此操作不可恢复。`)) return;
    setError(null);
    try {
      await agentCodeApi.deleteCase(caseItem.id);
      const list = await agentCodeApi.listCases(10);
      setCases(list);
      if (selectedCaseId === caseItem.id) {
        setSelectedCaseId(list[0]?.id ?? null);
      }
      if (run?.case_id === caseItem.id) {
        stopStreamRef.current?.();
        stopStreamRef.current = null;
        setRun(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Case 失败");
    }
  };

  useEffect(() => {
    void loadCases();
    void loadProviders();
    return () => stopStreamRef.current?.();
  }, [loadCases, loadProviders]);

  const handleStart = async () => {
    if (!selectedCaseId || running || batchRunning) return;
    stopStreamRef.current?.();
    setError(null);
    setRunning(true);
    try {
      const created = await agentCodeApi.startRun(selectedCaseId, selectedProvider || null, {
        enableVerifier,
      });
      setRun(created);
      stopStreamRef.current = agentCodeApi.streamRun(created.run_id, {
        onEvent: (event) => {
          if (event.type === "error") {
            setError(event.message || event.run?.error || "执行异常");
          } else if (event.type === "progress" || event.type === "start") {
            setError(null);
          } else if (event.type === "done" && event.run?.status === "failed") {
            setError(event.run.error || event.message || "执行失败");
          } else if (event.type === "done") {
            setError(null);
          }
          if (event.run) setRun(event.run);
        },
        onError: async (err) => {
          if (created.run_id) {
            try {
              const latest = await agentCodeApi.getRun(created.run_id);
              setRun(latest);
              if (latest.status === "failed" && latest.error) {
                setError(latest.error);
                return;
              }
            } catch {
              /* ignore */
            }
          }
          setError(err.message);
        },
        onDone: () => setRunning(false),
      });
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : "启动失败");
    }
  };

  const handleBatchStart = async () => {
    if (running || batchRunning) return;
    const all = await agentCodeApi.listCases(100);
    if (!all.length) {
      setError("没有可执行的 Case");
      return;
    }
    if (!window.confirm(`将顺序执行全部 ${all.length} 个 Case（pytest）。继续？`)) return;
    setBatchRunning(true);
    setRunning(true);
    setError(null);
    try {
      await agentCodeApi.startBatch(
        all.map((c) => c.id),
        selectedProvider || null,
        { enableVerifier: false }
      );
      await loadCases();
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量执行失败");
    } finally {
      setBatchRunning(false);
      setRunning(false);
    }
  };

  const handleAbort = async () => {
    if (aborting || !running) return;
    setAborting(true);
    try {
      stopStreamRef.current?.();
      stopStreamRef.current = null;
      if (run?.run_id) {
        const latest = await agentCodeApi.cancelRun(run.run_id);
        setRun(latest);
      }
      setRunning(false);
      setBatchRunning(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "中止失败");
    } finally {
      setAborting(false);
    }
  };

  const activeStep = focusStep;

  return (
    <section className="agent-test-page">
      <header className="agent-test-toolbar">
        <div className="agent-test-toolbar-left">
          <span className="agent-test-toolbar-title">AgentTest_Code</span>
          {run && (
            <span className="agent-test-run-badge">
              {run.case_name} · {run.status} · 步骤 {(activeStepOrder ?? run.current_step_index) + 1}/
              {run.total_steps}
              {run.llm_provider ? ` · ${run.llm_provider}` : ""}
            </span>
          )}
        </div>
        <div className="agent-test-toolbar-actions">
          <label className="agent-test-provider">
            <span>模型</span>
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              disabled={running || providers.length === 0}
            >
              {providers.length === 0 && <option value="">无可用模型</option>}
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="agent-verifier-toggle">
            <input
              type="checkbox"
              checked={enableVerifier}
              onChange={(e) => setEnableVerifier(e.target.checked)}
              disabled={running}
            />
            <span>验证</span>
          </label>
          <button className="secondary-btn" type="button" onClick={() => void loadCases()} disabled={loadingCases}>
            刷新
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
            disabled={running || !agentReady}
            onClick={() => void handleBatchStart()}
          >
            {batchRunning ? "批量中..." : "批量执行"}
          </button>
          <button
            className="secondary-btn"
            type="button"
            disabled={!running || aborting}
            onClick={() => void handleAbort()}
          >
            {aborting ? "中止中..." : "中止"}
          </button>
        </div>
      </header>

      {error && <div className="agent-test-error">{error}</div>}

      <div className="agent-test-grid">
        <section className="agent-panel agent-panel-cases">
          <header className="agent-panel-header">
            <h3>已保存 Case</h3>
            <span>含原始脚本一并入库</span>
          </header>
          <div className="agent-panel-body">
            <ul className="agent-case-list">
              {cases.map((item) => {
                const isSelected = selectedCaseId === item.id;
                const isRunningCase = run?.case_id === item.id;
                return (
                  <li
                    key={item.id}
                    className={isSelected ? "agent-case-block agent-case-block-active" : "agent-case-block"}
                  >
                    <div className="agent-case-item-row">
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
                      <button
                        type="button"
                        className="agent-case-delete-btn"
                        title="删除 Case"
                        disabled={running || batchRunning}
                        onClick={() => void handleDeleteCase(item)}
                      >
                        删除
                      </button>
                    </div>
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
            <h3>代码生成</h3>
            <span>截图 + UI XML → uiautomator2</span>
          </header>
          <div className="agent-panel-body agent-log-body">
            {!focusStep?.generated_code && (
              <div className="agent-panel-empty">
                {running ? "等待代码 Agent..." : "执行后显示本步生成代码"}
              </div>
            )}
            {focusStep?.generated_code && (
              <article className="agent-log-item">
                <div className="agent-log-meta">
                  <span>步骤 {(focusStep.step_order ?? 0) + 1}</span>
                  <span>{focusStep.status}</span>
                </div>
                <p>{focusStep.generated_code.reasoning || focusStep.description}</p>
                <pre className="agent-code-code-line">{focusStep.generated_code.code_line}</pre>
                {focusStep.generated_code.template_path && (
                  <small style={{ color: "#94a3b8" }}>模板：{focusStep.generated_code.template_path}</small>
                )}
                {focusStep.error && <pre className="agent-code-error">{focusStep.error}</pre>}
              </article>
            )}
            {historySteps
              .filter((step) => !focusStep || step.step_order !== focusStep.step_order)
              .map((step) => (
                <article key={step.step_order} className="agent-log-item">
                  <div className="agent-log-meta">
                    <span>步骤 {step.step_order + 1}</span>
                    <span>{step.status}</span>
                  </div>
                  <p>{step.generated_code?.reasoning || step.description}</p>
                  {step.generated_code?.code_line && (
                    <pre className="agent-code-code-line">{step.generated_code.code_line}</pre>
                  )}
                  {step.generated_code?.template_path && (
                    <small style={{ color: "#94a3b8" }}>模板：{step.generated_code.template_path}</small>
                  )}
                  {step.error && <pre className="agent-code-error">{step.error}</pre>}
                </article>
              ))}
          </div>
        </section>

        <section className="agent-panel agent-panel-logs">
          <header className="agent-panel-header">
            <h3>pytest 输出</h3>
          </header>
          <div className="agent-panel-body agent-log-body">
            {outputStep?.generated_code?.execution_output ? (
              <pre>{outputStep.generated_code.execution_output}</pre>
            ) : outputStep?.error ? (
              <pre className="agent-code-error">{outputStep.error}</pre>
            ) : (
              <div className="agent-panel-empty">
                {running ? "等待代码执行..." : "执行后显示 pytest / u2 日志"}
              </div>
            )}
          </div>
        </section>

        <section className="agent-panel agent-panel-images">
          <header className="agent-panel-header">
            <h3>执行截图</h3>
          </header>
          <div className="agent-panel-body agent-image-body">
            {galleryRun && (
              <AgentExecutionGallery
                attempts={galleryRun.attempts}
                steps={galleryRun.steps}
                runId={galleryRun.run_id}
                runStatus={galleryRun.status}
                agentRunning={running}
              />
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
