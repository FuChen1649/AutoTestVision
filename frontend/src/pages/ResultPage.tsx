import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { agentApi } from "../api/agent";
import { agentCodeApi } from "../api/agentCode";
import { reportsApi, type ReportCaseResult, type ReportDetail, type ReportSummary } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import { resultVerifyApi } from "../api/resultVerify";
import AgentExecutionGallery from "../components/AgentExecutionGallery";
import DualScriptVerifyPanel from "../components/DualScriptVerifyPanel";
import type { AgentRunState, ProviderInfo } from "../types/agent";
import { codeRunToGalleryRun } from "../types/agentCode";
import type { DualStepVerifyReview, VerifyStreamEvent } from "../types/resultVerify";
import "./PlatformPages.css";
import "./ResultPage.css";

type ExecModeFilter = "position" | "code" | "dual" | "all";

interface RunDetailEntry {
  execMode: "position" | "code";
  run: AgentRunState;
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

function statusClass(status: string) {
  if (status === "completed" || status === "success") return "result-status-success";
  if (status === "failed") return "result-status-failed";
  if (status === "running") return "result-status-running";
  if (status === "cancelled") return "result-status-cancelled";
  return "result-status-pending";
}

function statusLabel(status: string) {
  if (status === "completed" || status === "success") return "完成";
  if (status === "failed") return "失败";
  if (status === "running") return "执行中";
  if (status === "pending") return "待执行";
  if (status === "cancelled") return "已中止";
  return status;
}

function reportTitle(item: ReportSummary) {
  if (item.report_type === "dual") {
    return `[双脚本] ${item.case_name || `Case #${item.case_id}`}`;
  }
  if (item.report_type === "single") {
    return `[${item.exec_mode}] 单 Case · ${item.case_name || `Case #${item.case_id}`}`;
  }
  return `[${item.exec_mode}] 跑批 ${item.report_id.slice(0, 8)}`;
}

function logsHref(runUuid: string, execMode: string) {
  const source = execMode === "code" ? "code" : "position";
  return `/logs?run_uuid=${encodeURIComponent(runUuid)}&source=${source}`;
}

export default function ResultPage() {
  const [searchParams] = useSearchParams();
  const [execMode, setExecMode] = useState<ExecModeFilter>(() => {
    const mode = searchParams.get("mode");
    if (mode === "position" || mode === "code" || mode === "dual") return mode;
    return "all";
  });
  const stopVerifyStreamRef = useRef<(() => void) | null>(null);
  const [reportItems, setReportItems] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedReportKey, setExpandedReportKey] = useState<string | null>(null);
  const [reportDetails, setReportDetails] = useState<Record<string, ReportDetail>>({});
  const [expandedResultKey, setExpandedResultKey] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, RunDetailEntry>>({});
  const [loadingReportId, setLoadingReportId] = useState<string | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [verifyingBatchId, setVerifyingBatchId] = useState<string | null>(null);
  const [verifyingRunId, setVerifyingRunId] = useState<string | null>(null);
  const [verifyingStepOrder, setVerifyingStepOrder] = useState<number | null>(null);
  const [verifyingDualTaskId, setVerifyingDualTaskId] = useState<string | null>(null);
  const [verifyingDualStepOrder, setVerifyingDualStepOrder] = useState<number | null>(null);
  const [dualVerifyReviews, setDualVerifyReviews] = useState<Record<string, DualStepVerifyReview[]>>({});
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");

  const reportKey = (item: ReportSummary) => `${item.exec_mode}:${item.report_id}`;

  const loadProviders = useCallback(async () => {
    try {
      const resp = await agentApi.listProviders();
      const reachable = resp.providers.filter((item) => item.available);
      setProviders(reachable);
      setSelectedProvider((current) => {
        if (current && reachable.some((p) => p.id === current)) return current;
        if (resp.default && reachable.some((p) => p.id === resp.default)) return resp.default;
        return reachable[0]?.id ?? "";
      });
    } catch (err) {
      if (!isApiOfflineError(err)) console.warn("加载模型列表失败", err);
    }
  }, []);

  const verifying =
    verifyingBatchId !== null || verifyingRunId !== null || verifyingDualTaskId !== null;

  const loadReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await reportsApi.list(
        execMode === "all" ? undefined : execMode === "dual" ? "dual" : execMode
      );
      setReportItems(resp.items);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载报告失败");
      }
    } finally {
      setLoading(false);
    }
  }, [execMode]);

  useEffect(() => {
    void loadReports();
    void loadProviders();
    return () => stopVerifyStreamRef.current?.();
  }, [loadReports, loadProviders]);

  const refreshRun = useCallback(async (runId: string, mode: "position" | "code") => {
    if (mode === "code") {
      const codeRun = await agentCodeApi.getRun(runId);
      const galleryRun = codeRunToGalleryRun(codeRun);
      setRunDetails((prev) => ({ ...prev, [runId]: { execMode: "code", run: galleryRun } }));
      return galleryRun;
    }
    const run = await agentApi.getRun(runId);
    setRunDetails((prev) => ({ ...prev, [runId]: { execMode: "position", run } }));
    return run;
  }, []);

  const openRun = useCallback(
    async (reportId: string, execModeValue: "position" | "code", runId: string, parentKey?: string) => {
      const resultKey = parentKey ? `${parentKey}:${runId}` : `${reportKey({ report_id: reportId, exec_mode: execModeValue } as ReportSummary)}:${runId}`;
      if (expandedResultKey === resultKey) {
        setExpandedResultKey(null);
        return;
      }
      setExpandedResultKey(resultKey);
      if (runDetails[runId]) return;
      setLoadingRunId(runId);
      try {
        await refreshRun(runId, execModeValue);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载执行详情失败");
      } finally {
        setLoadingRunId(null);
      }
    },
    [expandedResultKey, refreshRun, runDetails]
  );

  const ensureReportDetail = useCallback(
    async (item: ReportSummary) => {
      const key = reportKey(item);
      if (reportDetails[key]) return reportDetails[key];
      setLoadingReportId(item.report_id);
      try {
        const detail = await reportsApi.get(
          item.report_id,
          item.report_type === "dual" ? "dual" : item.exec_mode
        );
        setReportDetails((prev) => ({ ...prev, [key]: detail }));
        if (detail.dual_reviews?.length) {
          setDualVerifyReviews((prev) => ({
            ...prev,
            [item.report_id]: detail.dual_reviews as DualStepVerifyReview[],
          }));
        }
        return detail;
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载报告详情失败");
        return null;
      } finally {
        setLoadingReportId(null);
      }
    },
    [reportDetails]
  );

  const toggleReport = useCallback(
    async (item: ReportSummary) => {
      const key = reportKey(item);
      if (expandedReportKey === key) {
        setExpandedReportKey(null);
        setExpandedResultKey(null);
        return;
      }
      setExpandedReportKey(key);
      setExpandedResultKey(null);

      if (item.report_type === "single" && item.run_uuid) {
        await openRun(item.report_id, item.exec_mode as "position" | "code", item.run_uuid, key);
        return;
      }
      await ensureReportDetail(item);
    },
    [ensureReportDetail, expandedReportKey, openRun]
  );

  useEffect(() => {
    const batchId = searchParams.get("batchId");
    const runId = searchParams.get("runId");
    const taskId = searchParams.get("taskId");
    const mode = searchParams.get("mode") as "position" | "code" | "dual" | null;
    if (!batchId && !runId && !taskId) return;
    if (reportItems.length === 0) return;

    void (async () => {
      if (taskId) {
        const item = reportItems.find((r) => r.report_id === taskId && r.report_type === "dual");
        if (item) {
          await toggleReport(item);
        }
        return;
      }

      if (runId) {
        const item = reportItems.find((r) => r.run_uuid === runId || r.report_id === runId);
        if (item) {
          await toggleReport(item);
        } else if (mode === "code" || mode === "position") {
          const synthetic: ReportSummary = {
            report_id: runId,
            report_type: "single",
            exec_mode: mode,
            status: "completed",
            total_cases: 1,
            passed_cases: 0,
            failed_cases: 0,
            completed_cases: 1,
            serial: null,
            case_id: null,
            case_name: null,
            run_uuid: runId,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };
          setExpandedReportKey(reportKey(synthetic));
          await openRun(runId, mode, runId);
        }
        return;
      }
      if (batchId) {
        const item = reportItems.find((r) => r.report_id === batchId && r.report_type === "batch");
        if (item) await toggleReport(item);
      }
    })();
  }, [searchParams, reportItems, toggleReport, openRun]);

  const applyVerifyStreamEvent = (event: VerifyStreamEvent) => {
    const mode = event.exec_mode ?? "position";
    if (event.type === "error") setError(event.message || "验证失败");
    if (event.type === "run_start" && event.run_id) {
      setVerifyingRunId(event.run_id);
      setVerifyingStepOrder(null);
    }
    if (event.type === "step_start" && event.step_order != null) setVerifyingStepOrder(event.step_order);
    if (mode === "position" || mode === "code") {
      if (event.type === "step_done" && event.run_id) {
        void refreshRun(event.run_id, mode);
        setVerifyingStepOrder(null);
      }
      if (event.type === "run_done" && event.run_id) {
        void refreshRun(event.run_id, mode);
        setVerifyingStepOrder(null);
        setVerifyingRunId(null);
      }
      if (event.type === "done" && event.run_id) {
        void refreshRun(event.run_id, mode);
        setVerifyingStepOrder(null);
        setVerifyingRunId(null);
      }
    }
  };

  const finishVerify = () => {
    stopVerifyStreamRef.current = null;
    setVerifyingBatchId(null);
    setVerifyingRunId(null);
    setVerifyingStepOrder(null);
    setVerifyingDualTaskId(null);
    setVerifyingDualStepOrder(null);
  };

  const applyDualVerifyStreamEvent = (event: VerifyStreamEvent) => {
    if (event.type === "error") setError(event.message || "双脚本验证失败");
    if (event.type === "step_start" && event.step_order != null) {
      setVerifyingDualStepOrder(event.step_order);
    }
    if (event.type === "step_done" && event.task_id && event.dual_review) {
      setDualVerifyReviews((prev) => {
        const current = prev[event.task_id!] ?? [];
        const merged = current.filter((item) => item.step_order !== event.dual_review!.step_order);
        return {
          ...prev,
          [event.task_id!]: [...merged, event.dual_review!].sort((a, b) => a.step_order - b.step_order),
        };
      });
      setVerifyingDualStepOrder(null);
    }
    if (event.type === "done" || event.type === "error") {
      setVerifyingDualStepOrder(null);
      setVerifyingDualTaskId(null);
    }
  };

  const handleVerifyDual = (taskId: string) => {
    if (!selectedProvider) return;
    setError(null);
    stopVerifyStreamRef.current?.();
    setVerifyingBatchId(null);
    setVerifyingRunId(null);
    setVerifyingStepOrder(null);
    setVerifyingDualTaskId(taskId);
    setVerifyingDualStepOrder(null);
    stopVerifyStreamRef.current = resultVerifyApi.streamVerifyDual(taskId, selectedProvider, {
      onEvent: applyDualVerifyStreamEvent,
      onError: (err) => setError(err.message),
      onDone: finishVerify,
    });
  };

  const handleVerifyBatch = (batchId: string, execMode: "position" | "code" = "position") => {
    if (!selectedProvider) return;
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
            const mode = event.exec_mode ?? execMode;
            if (mode === "position" || mode === "code") {
              void refreshRun(event.run_id, mode);
            }
          }
        },
        onError: (err) => setError(err.message),
        onDone: finishVerify,
      },
      execMode
    );
  };

  const handleVerifyRun = (runId: string) => {
    if (!selectedProvider) return;
    setError(null);
    stopVerifyStreamRef.current?.();
    setVerifyingBatchId(null);
    setVerifyingRunId(runId);
    setVerifyingStepOrder(null);
    stopVerifyStreamRef.current = resultVerifyApi.streamVerifyRun(runId, selectedProvider, {
      onEvent: applyVerifyStreamEvent,
      onError: (err) => setError(err.message),
      onDone: finishVerify,
    });
  };

  const renderCaseResult = (
    item: ReportCaseResult,
    execModeValue: "position" | "code",
    parentKey: string,
    options?: { caseOrder?: number; showVerify?: boolean; pathLabel?: string }
  ) => {
    const runId = item.run_uuid;
    const modeValue = (item.exec_mode === "code" ? "code" : execModeValue) as "position" | "code";
    const displayName = options?.pathLabel
      ? `${options.pathLabel} · ${item.case_name}`
      : item.case_name;
    const resultKey = `${parentKey}:${runId}`;
    const resultExpanded = expandedResultKey === resultKey;
    const entry = runDetails[runId];
    const run = entry?.run;
    const isCurrentRunVerifying = verifyingRunId === runId;
    const caseVerifyDone =
      !isCurrentRunVerifying && Boolean(run?.steps.some((step) => step.purpose_review));

    return (
      <div key={resultKey} className={resultExpanded ? "result-item result-item-open" : "result-item"}>
        <div className="result-item-header-row">
          <button
            type="button"
            className="result-item-header"
            onClick={() => void openRun(item.run_uuid, modeValue, runId, parentKey)}
          >
            <span className="result-batch-chevron">{resultExpanded ? "▾" : "▸"}</span>
            <div className="result-item-summary">
              <strong>
                {options?.caseOrder != null ? `${options.caseOrder + 1}. ` : ""}
                {displayName}
              </strong>
              <span>
                Case #{item.case_id} · 步骤 {item.passed_steps}/{item.total_steps}
                {item.error ? ` · ${item.error}` : ""}
              </span>
            </div>
            <span className={`result-status ${statusClass(item.status)}`}>{statusLabel(item.status)}</span>
          </button>
          {options?.showVerify && (
            <button
              type="button"
              className="result-verify-btn"
              disabled={
                !selectedProvider ||
                verifyingBatchId !== null ||
                (verifyingRunId !== null && verifyingRunId !== runId)
              }
              onClick={() => void handleVerifyRun(runId)}
              title="分析该 Case 各步执行目的"
            >
              {isCurrentRunVerifying ? "验证中..." : caseVerifyDone ? "已验证" : "验证"}
            </button>
          )}
          <Link className="result-verify-btn" to={logsHref(runId, modeValue)} title="查看执行日志">
            日志
          </Link>
        </div>

        {resultExpanded && (
          <div className="result-item-body">
            {loadingRunId === runId && !run && <div className="result-empty">加载截图与回放数据...</div>}
            {run && (
              <AgentExecutionGallery
                attempts={run.attempts}
                steps={run.steps}
                runId={run.run_id}
                runStatus={run.status}
                agentRunning={false}
                verifyingStepOrder={isCurrentRunVerifying ? verifyingStepOrder : null}
                allowDeviceReplay
                deviceReplayMode={modeValue}
                logsHref={logsHref(runId, modeValue)}
              />
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <section className="result-page">
      <header className="result-toolbar">
        <div>
          <h2>报告中心</h2>
          <p>跑批与单 Case 报告含回放；双脚本报告可逐步比对 Position / Code 截图一致性</p>
        </div>
        <div className="result-toolbar-actions">
          <label className="result-provider">
            <span>模型</span>
            <select
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value)}
              disabled={verifying || providers.length === 0}
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
          <button className="secondary-btn" type="button" onClick={() => void loadReports()} disabled={loading}>
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </header>

      <div className="platform-tabs" style={{ padding: "0 0 12px" }}>
        {(["all", "dual", "position", "code"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            className={execMode === mode ? "platform-tab active" : "platform-tab"}
            onClick={() => setExecMode(mode)}
          >
            {mode === "all"
              ? "全部"
              : mode === "dual"
                ? "双脚本"
                : mode === "position"
                  ? "Position"
                  : "Code"}
          </button>
        ))}
      </div>

      {error && <div className="result-error">{error}</div>}

      <div className="result-list">
        {loading && reportItems.length === 0 && <div className="result-empty">加载中...</div>}
        {!loading && reportItems.length === 0 && <div className="result-empty">暂无执行报告</div>}

        {reportItems.map((item) => {
          const key = reportKey(item);
          const expanded = expandedReportKey === key;
          const detail = reportDetails[key];
          const batchVerifying = verifyingBatchId === item.report_id;
          const dualVerifying = verifyingDualTaskId === item.report_id;
          const dualReviews = dualVerifyReviews[item.report_id] ?? [];
          const dualVerifyDone =
            !dualVerifying && dualReviews.length > 0 && item.report_type === "dual";
          const isBatch = item.report_type === "batch";
          const isDual = item.report_type === "dual";
          const mode = item.exec_mode as "position" | "code" | "dual";

          return (
            <article key={key} className={expanded ? "result-batch result-batch-open" : "result-batch"}>
              <div className="result-batch-header-row">
                <button type="button" className="result-batch-header" onClick={() => void toggleReport(item)}>
                  <span className="result-batch-chevron">{expanded ? "▾" : "▸"}</span>
                  <div className="result-batch-summary">
                    <strong>{reportTitle(item)}</strong>
                    <span>
                      {formatDateTime(item.created_at)} ·{" "}
                      {isBatch
                        ? `${item.total_cases} Case · 通过 ${item.passed_cases} / 失败 ${item.failed_cases}`
                        : isDual
                          ? `Case #${item.case_id} · Position + Code 双路径`
                          : `Case #${item.case_id} · ${item.serial ?? "—"}`}
                    </span>
                  </div>
                  <span className={`result-status ${statusClass(item.status)}`}>{statusLabel(item.status)}</span>
                </button>
                {isDual && (
                  <button
                    type="button"
                    className="result-verify-btn"
                    disabled={
                      dualVerifying ||
                      (item.status !== "completed" && item.status !== "success") ||
                      !selectedProvider ||
                      verifyingBatchId !== null ||
                      verifyingRunId !== null
                    }
                    onClick={() => void handleVerifyDual(item.report_id)}
                    title="逐步比对 Position 与 Code 同步骤截图是否一致"
                  >
                    {dualVerifying ? "验证中..." : dualVerifyDone ? "已验证" : "双脚本验证"}
                  </button>
                )}
                {isBatch && (mode === "position" || mode === "code") && (
                  <button
                    type="button"
                    className="result-verify-btn"
                    disabled={batchVerifying || item.completed_cases === 0 || !selectedProvider}
                    onClick={() => void handleVerifyBatch(item.report_id, mode)}
                    title="分析本批次所有 Case 各步执行目的"
                  >
                    {batchVerifying ? "验证中..." : "验证"}
                  </button>
                )}
                {item.run_uuid && (
                  <Link className="result-verify-btn" to={logsHref(item.run_uuid, mode)} title="查看执行日志">
                    日志
                  </Link>
                )}
              </div>

              {expanded && (
                <div className="result-batch-body">
                  {loadingReportId === item.report_id && !detail && item.report_type === "batch" && (
                    <div className="result-empty">加载报告详情...</div>
                  )}
                  {isBatch &&
                    detail?.case_results.map((caseItem, index) =>
                      renderCaseResult(caseItem, mode === "dual" ? "position" : mode, key, {
                        caseOrder: index,
                        showVerify: true,
                      })
                    )}
                  {isDual && (
                    <DualScriptVerifyPanel
                      reviews={dualReviews}
                      verifyingStepOrder={dualVerifying ? verifyingDualStepOrder : null}
                      active={dualVerifying || dualReviews.length > 0}
                    />
                  )}
                  {isDual &&
                    detail?.case_results.map((caseItem, index) =>
                      renderCaseResult(caseItem, (caseItem.exec_mode === "code" ? "code" : "position"), key, {
                        caseOrder: index,
                        showVerify: false,
                        pathLabel: caseItem.path_label ?? (caseItem.exec_mode === "code" ? "Code" : "Position"),
                      })
                    )}
                  {item.report_type === "single" && item.run_uuid && (
                    <>
                      {loadingRunId === item.run_uuid && !runDetails[item.run_uuid] && (
                        <div className="result-empty">加载截图与回放数据...</div>
                      )}
                      {runDetails[item.run_uuid] &&
                        renderCaseResult(
                          {
                            case_id: item.case_id ?? 0,
                            case_name: item.case_name ?? "单 Case",
                            status: item.status,
                            run_uuid: item.run_uuid,
                            total_steps: runDetails[item.run_uuid].run.total_steps,
                            passed_steps: runDetails[item.run_uuid].run.steps.filter((s) => s.status === "success")
                              .length,
                            error: runDetails[item.run_uuid].run.error,
                          },
                          item.exec_mode === "code" ? "code" : "position",
                          key,
                          { showVerify: item.exec_mode === "position" }
                        )}
                    </>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
