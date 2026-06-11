import { useCallback, useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import { isApiOfflineError } from "../api/http";
import AgentExecutionGallery from "../components/AgentExecutionGallery";
import type { AgentRunState, BatchListItem, BatchState } from "../types/agent";
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
  const [batches, setBatches] = useState<BatchListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);
  const [batchDetails, setBatchDetails] = useState<Record<string, BatchState>>({});
  const [expandedResultKey, setExpandedResultKey] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, AgentRunState>>({});
  const [loadingBatchId, setLoadingBatchId] = useState<string | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await agentApi.listBatches(50);
      setBatches(list);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载批量结果失败");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBatches();
  }, [loadBatches]);

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
      const run = await agentApi.getRun(runId);
      setRunDetails((prev) => ({ ...prev, [runId]: run }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载执行详情失败");
    } finally {
      setLoadingRunId(null);
    }
  };

  return (
    <section className="result-page">
      <header className="result-toolbar">
        <div>
          <h2>批量执行结果</h2>
          <p>按批次查看 Case 执行结果，支持虚拟回放与真机回放</p>
        </div>
        <button className="secondary-btn" type="button" onClick={() => void loadBatches()} disabled={loading}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      {error && <div className="result-error">{error}</div>}

      <div className="result-list">
        {loading && batches.length === 0 && <div className="result-empty">加载中...</div>}
        {!loading && batches.length === 0 && <div className="result-empty">暂无批量执行记录</div>}

        {batches.map((batch) => {
          const expanded = expandedBatchId === batch.batch_id;
          const detail = batchDetails[batch.batch_id];
          return (
            <article key={batch.batch_id} className={expanded ? "result-batch result-batch-open" : "result-batch"}>
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
                    return (
                      <div
                        key={item.result_id}
                        className={resultExpanded ? "result-item result-item-open" : "result-item"}
                      >
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
