import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { agentApi } from "../api/agent";
import { reportsApi } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import { resultVerifyApi } from "../api/resultVerify";
import AgentExecutionGallery from "../components/AgentExecutionGallery";
import type { AgentRunState, BatchListItem, BatchState, ProviderInfo } from "../types/agent";
import type { VerifyStreamEvent } from "../types/resultVerify";
import "./PlatformPages.css";
import "./ResultPage.css";

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

function statusClass(status: string) {
  if (status === "completed") return "result-status-success";
  if (status === "failed") return "result-status-failed";
  if (status === "running") return "result-status-running";
  if (status === "cancelled") return "result-status-cancelled";
  return "result-status-pending";
}

function statusLabel(status: string) {
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "running") return "执行中";
  if (status === "pending") return "待执行";
  if (status === "cancelled") return "已中止";
  return status;
}

export default function ResultPage() {
  const [searchParams] = useSearchParams();
  const [execMode, setExecMode] = useState<"position" | "code" | "all">(
    (searchParams.get("mode") as "position" | "code") ?? "all"
  );
  const stopVerifyStreamRef = useRef<(() => void) | null>(null);
  const [batches, setBatches] = useState<BatchListItem[]>([]);
  const [reportItems, setReportItems] = useState<
    { report_id: string; exec_mode: string; status: string; total_cases: number; passed_cases: number; failed_cases: number; created_at: string }[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);
  const [batchDetails, setBatchDetails] = useState<Record<string, BatchState>>({});
  const [expandedResultKey, setExpandedResultKey] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, AgentRunState>>({});
  const [loadingBatchId, setLoadingBatchId] = useState<string | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [verifyingBatchId, setVerifyingBatchId] = useState<string | null>(null);
  const [verifyingRunId, setVerifyingRunId] = useState<string | null>(null);
  const [verifyingStepOrder, setVerifyingStepOrder] = useState<number | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");

  const loadProviders = useCallback(async () => {
    try {
      const resp = await agentApi.listProviders();
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

  const verifying = verifyingBatchId !== null || verifyingRunId !== null;

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (execMode === "position") {
        const list = await agentApi.listBatches(50);
        setBatches(list);
        setReportItems([]);
      } else {
        const resp = await reportsApi.list(execMode === "all" ? undefined : execMode);
        setReportItems(resp.items);
        setBatches([]);
      }
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载批量结果失败");
      }
    } finally {
      setLoading(false);
    }
  }, [execMode]);

  useEffect(() => {
    void loadBatches();
    void loadProviders();
    return () => stopVerifyStreamRef.current?.();
  }, [loadBatches, loadProviders]);

  const applyVerifyStreamEvent = (event: VerifyStreamEvent) => {
    if (event.type === "error") {
      setError(event.message || "验证失败");
    }
    if (event.type === "run_start" && event.run_id) {
      setVerifyingRunId(event.run_id);
      setVerifyingStepOrder(null);
    }
    if (event.type === "step_start" && event.step_order != null) {
      setVerifyingStepOrder(event.step_order);
    }
    if (event.type === "step_done" && event.run) {
      setRunDetails((prev) => ({ ...prev, [event.run!.run_id]: event.run! }));
      setVerifyingStepOrder(null);
    }
    if (event.type === "run_done") {
      if (event.run) {
        setRunDetails((prev) => ({ ...prev, [event.run!.run_id]: event.run! }));
      }
      setVerifyingStepOrder(null);
      setVerifyingRunId(null);
    }
  };

  const finishVerify = () => {
    stopVerifyStreamRef.current = null;
    setVerifyingBatchId(null);
    setVerifyingRunId(null);
    setVerifyingStepOrder(null);
  };

  const ensureRunLoaded = async (batchId: string, runId: string) => {
    setExpandedResultKey(`${batchId}:${runId}`);
    if (!runDetails[runId]) {
      await refreshRun(runId);
    }
  };

  const refreshRun = async (runId: string) => {
    const run = await agentApi.getRun(runId);
    setRunDetails((prev) => ({ ...prev, [runId]: run }));
    return run;
  };

  const toggleBatch = async (batchId: string) => {
    if (expandedBatchId === batchId) {
      setExpandedBatchId(null);
      setExpandedResultKey(null);
      return;
    }

    setExpandedBatchId(batchId);
    setExpandedResultKey(null);
    if (batchDetails[batchId]) {
      return;
    }

    setLoadingBatchId(batchId);
    try {
      const detail = await agentApi.getBatch(batchId);
      setBatchDetails((prev) => ({ ...prev, [batchId]: detail }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载批量详情失败");
    } finally {
      setLoadingBatchId(null);
    }
  };

  const toggleResult = async (batchId: string, runId: string) => {
    const key = `${batchId}:${runId}`;
    if (expandedResultKey === key) {
      setExpandedResultKey(null);
      return;
    }

    setExpandedResultKey(key);
    if (runDetails[runId]) {
      return;
    }

    setLoadingRunId(runId);
    try {
      await refreshRun(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载执行详情失败");
    } finally {
      setLoadingRunId(null);
    }
  };

  const handleVerifyBatch = (batchId: string) => {
    if (!selectedProvider) {
      return;
    }
    setError(null);
    stopVerifyStreamRef.current?.();
    setVerifyingBatchId(batchId);
    setVerifyingRunId(null);
    setVerifyingStepOrder(null);

    stopVerifyStreamRef.current = resultVerifyApi.streamVerifyBatch(
      batchId,
      selectedProvider,
      {
        onEvent: (event) => {
          applyVerifyStreamEvent(event);
          if (event.type === "run_start" && event.run_id) {
            void ensureRunLoaded(batchId, event.run_id);
          }
        },
        onError: (err) => setError(err.message),
        onDone: finishVerify,
      }
    );
  };

  const handleVerifyRun = (runId: string, batchId?: string) => {
    if (!selectedProvider) {
      return;
    }
    setError(null);
    stopVerifyStreamRef.current?.();
    setVerifyingBatchId(null);
    setVerifyingRunId(runId);
    setVerifyingStepOrder(null);
    if (batchId) {
      void ensureRunLoaded(batchId, runId);
    }

    stopVerifyStreamRef.current = resultVerifyApi.streamVerifyRun(runId, selectedProvider, {
      onEvent: applyVerifyStreamEvent,
      onError: (err) => setError(err.message),
      onDone: finishVerify,
    });
  };

  return (
    <section className="result-page">
      <header className="result-toolbar">
        <div>
          <h2>批量执行结果</h2>
          <p>按批次查看 Case 执行结果，支持虚拟回放、真机回放与执行目的验证</p>
        </div>
        <div className="result-toolbar-actions">
          <label className="result-provider">
            <span>模型</span>
            <select
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value)}
              disabled={verifying || providers.length === 0}
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
              className="result-provider-refresh"
              onClick={() => void loadProviders()}
              disabled={verifying}
              title="重新探测模型可达性"
            >
              ↻
            </button>
          </label>
          <button className="secondary-btn" type="button" onClick={() => void loadBatches()} disabled={loading}>
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </header>

      <div className="platform-tabs" style={{ padding: "0 0 12px" }}>
        {(["all", "position", "code"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            className={execMode === mode ? "platform-tab active" : "platform-tab"}
            onClick={() => setExecMode(mode)}
          >
            {mode === "all" ? "全部" : mode === "position" ? "Position" : "Code"}
          </button>
        ))}
      </div>

      {error && <div className="result-error">{error}</div>}

      <div className="result-list">
        {loading && batches.length === 0 && reportItems.length === 0 && (
          <div className="result-empty">加载中...</div>
        )}
        {!loading && batches.length === 0 && reportItems.length === 0 && (
          <div className="result-empty">暂无批量执行记录</div>
        )}

        {execMode !== "position" &&
          reportItems.map((item) => (
            <article key={`${item.exec_mode}-${item.report_id}`} className="result-batch">
              <div className="result-batch-header-row">
                <div className="result-batch-header">
                  <div className="result-batch-summary">
                    <strong>
                      [{item.exec_mode}] 批次 {item.report_id.slice(0, 8)}
                    </strong>
                    <span>
                      {formatDateTime(item.created_at)} · {item.total_cases} Case · 通过 {item.passed_cases} / 失败{" "}
                      {item.failed_cases}
                    </span>
                  </div>
                  <span className={`result-status ${statusClass(item.status)}`}>{statusLabel(item.status)}</span>
                </div>
              </div>
            </article>
          ))}

        {execMode !== "code" &&
          batches.map((batch) => {
          const expanded = expandedBatchId === batch.batch_id;
          const detail = batchDetails[batch.batch_id];
          const batchVerifying = verifyingBatchId === batch.batch_id;
          return (
            <article key={batch.batch_id} className={expanded ? "result-batch result-batch-open" : "result-batch"}>
              <div className="result-batch-header-row">
                <button
                  type="button"
                  className="result-batch-header"
                  onClick={() => void toggleBatch(batch.batch_id)}
                >
                  <span className="result-batch-chevron">{expanded ? "▾" : "▸"}</span>
                  <div className="result-batch-summary">
                    <strong>批次 {batch.batch_id.slice(0, 8)}</strong>
                    <span>
                      {formatDateTime(batch.created_at)} · {batch.total_cases} 个 Case · 通过{" "}
                      {batch.passed_cases} / 失败 {batch.failed_cases}
                      {batch.llm_provider ? ` · ${batch.llm_provider}` : ""}
                    </span>
                  </div>
                  <span className={`result-status ${statusClass(batch.status)}`}>{statusLabel(batch.status)}</span>
                </button>
                <button
                  type="button"
                  className="result-verify-btn"
                  disabled={batchVerifying || batch.completed_cases === 0 || !selectedProvider}
                  onClick={() => void handleVerifyBatch(batch.batch_id)}
                  title="分析本批次所有 Case 各步执行目的"
                >
                  {batchVerifying ? "验证中..." : "验证"}
                </button>
              </div>

              {expanded && (
                <div className="result-batch-body">
                  {loadingBatchId === batch.batch_id && !detail && (
                    <div className="result-empty">加载批次详情...</div>
                  )}
                  {detail && detail.results.length === 0 && (
                    <div className="result-empty">该批次尚无 Case 结果</div>
                  )}
                  {detail?.results.map((item) => {
                    const resultKey = `${batch.batch_id}:${item.run_id}`;
                    const resultExpanded = expandedResultKey === resultKey;
                    const run = runDetails[item.run_id];
                    const isCurrentRunVerifying = verifyingRunId === item.run_id;
                    const caseVerifying = isCurrentRunVerifying;
                    const caseVerifyDone =
                      !caseVerifying &&
                      Boolean(run?.steps.some((step) => step.purpose_review));
                    return (
                      <div
                        key={item.result_id}
                        className={resultExpanded ? "result-item result-item-open" : "result-item"}
                      >
                        <div className="result-item-header-row">
                          <button
                            type="button"
                            className="result-item-header"
                            onClick={() => void toggleResult(batch.batch_id, item.run_id)}
                          >
                            <span className="result-batch-chevron">{resultExpanded ? "▾" : "▸"}</span>
                            <div className="result-item-summary">
                              <strong>
                                {item.case_order + 1}. {item.case_name}
                              </strong>
                              <span>
                                Case #{item.case_id} · 步骤 {item.passed_steps}/{item.total_steps}
                                {item.error ? ` · ${item.error}` : ""}
                              </span>
                            </div>
                            <span className={`result-status ${statusClass(item.status)}`}>
                              {statusLabel(item.status)}
                            </span>
                          </button>
                          <button
                            type="button"
                            className="result-verify-btn"
                            disabled={
                              !selectedProvider ||
                              batchVerifying ||
                              (verifyingRunId !== null && verifyingRunId !== item.run_id)
                            }
                            onClick={() => void handleVerifyRun(item.run_id, batch.batch_id)}
                            title="分析该 Case 各步执行目的"
                          >
                            {caseVerifying
                              ? "验证中..."
                              : caseVerifyDone
                                ? "已验证"
                                : "验证"}
                          </button>
                        </div>

                        {resultExpanded && (
                          <div className="result-item-body">
                            {loadingRunId === item.run_id && !run && (
                              <div className="result-empty">加载截图与回放数据...</div>
                            )}
                            {run && (
                              <AgentExecutionGallery
                                attempts={run.attempts}
                                steps={run.steps}
                                runId={run.run_id}
                                runStatus={run.status}
                                agentRunning={false}
                                verifyingStepOrder={
                                  isCurrentRunVerifying ? verifyingStepOrder : null
                                }
                              />
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
