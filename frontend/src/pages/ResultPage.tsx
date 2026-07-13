import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [selectedReportKey, setSelectedReportKey] = useState<string | null>(null);
  const [reportDetails, setReportDetails] = useState<Record<string, ReportDetail>>({});
  const [focusedRunId, setFocusedRunId] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<Record<string, RunDetailEntry>>({});
  const [loadingReportId, setLoadingReportId] = useState<string | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const autoSelectedRef = useRef(false);
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

  const reportStats = useMemo(() => {
    const dual = reportItems.filter((i) => i.report_type === "dual").length;
    const batch = reportItems.filter((i) => i.report_type === "batch").length;
    const failed = reportItems.filter((i) => i.status === "failed").length;
    const ok = reportItems.filter((i) => i.status === "completed" || i.status === "success").length;
    return { total: reportItems.length, dual, batch, failed, ok };
  }, [reportItems]);

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

  const loadRun = useCallback(
    async (execModeValue: "position" | "code", runId: string) => {
      setFocusedRunId(runId);
      if (runDetails[runId]) return runDetails[runId].run;
      setLoadingRunId(runId);
      try {
        return await refreshRun(runId, execModeValue);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载执行详情失败");
        return null;
      } finally {
        setLoadingRunId(null);
      }
    },
    [refreshRun, runDetails]
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

  const selectReport = useCallback(
    async (item: ReportSummary) => {
      const key = reportKey(item);
      setSelectedReportKey(key);
      setFocusedRunId(null);

      if (item.report_type === "single" && item.run_uuid) {
        await loadRun(item.exec_mode as "position" | "code", item.run_uuid);
        return;
      }

      const detail = await ensureReportDetail(item);
      if (!detail) return;

      // 默认加载第一条可展示的 run，右侧立刻有内容
      const first = detail.case_results[0];
      if (first?.run_uuid) {
        const mode =
          first.exec_mode === "code" || item.exec_mode === "code" ? "code" : "position";
        await loadRun(mode, first.run_uuid);
      }
    },
    [ensureReportDetail, loadRun]
  );

  // 筛选变化时允许重新自动选中
  useEffect(() => {
    autoSelectedRef.current = false;
    setSelectedReportKey(null);
    setFocusedRunId(null);
  }, [execMode]);

  // 列表加载后自动选中第一条（或 URL 指定项）
  useEffect(() => {
    if (reportItems.length === 0) return;
    const batchId = searchParams.get("batchId");
    const runId = searchParams.get("runId");
    const taskId = searchParams.get("taskId");
    const mode = searchParams.get("mode") as "position" | "code" | "dual" | null;

    void (async () => {
      if (taskId) {
        const item = reportItems.find((r) => r.report_id === taskId && r.report_type === "dual");
        if (item) {
          await selectReport(item);
          autoSelectedRef.current = true;
        }
        return;
      }
      if (runId) {
        const item = reportItems.find((r) => r.run_uuid === runId || r.report_id === runId);
        if (item) {
          await selectReport(item);
          autoSelectedRef.current = true;
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
          setSelectedReportKey(reportKey(synthetic));
          await loadRun(mode, runId);
          autoSelectedRef.current = true;
        }
        return;
      }
      if (batchId) {
        const item = reportItems.find((r) => r.report_id === batchId && r.report_type === "batch");
        if (item) {
          await selectReport(item);
          autoSelectedRef.current = true;
        }
        return;
      }
      if (!autoSelectedRef.current) {
        await selectReport(reportItems[0]);
        autoSelectedRef.current = true;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在列表/URL 变化时自动选中
  }, [searchParams, reportItems]);

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
    options?: { caseOrder?: number; showVerify?: boolean; pathLabel?: string }
  ) => {
    const runId = item.run_uuid;
    const modeValue = (item.exec_mode === "code" ? "code" : execModeValue) as "position" | "code";
    const displayName = options?.pathLabel
      ? `${options.pathLabel} · ${item.case_name}`
      : item.case_name;
    const focused = focusedRunId === runId;
    const entry = runDetails[runId];
    const run = entry?.run;
    const isCurrentRunVerifying = verifyingRunId === runId;
    const caseVerifyDone =
      !isCurrentRunVerifying && Boolean(run?.steps.some((step) => step.purpose_review));

    return (
      <div key={runId} className={focused ? "result-item result-item-open" : "result-item"}>
        <div className="result-item-header-row">
          <button
            type="button"
            className="result-item-header"
            onClick={() => void loadRun(modeValue, runId)}
          >
            <span className="result-batch-chevron">{focused ? "●" : "○"}</span>
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

        {focused && (
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

  const selectedItem = reportItems.find((item) => reportKey(item) === selectedReportKey) ?? null;
  const selectedDetail = selectedItem ? reportDetails[reportKey(selectedItem)] : null;
  const selectedIsBatch = selectedItem?.report_type === "batch";
  const selectedIsDual = selectedItem?.report_type === "dual";
  const selectedIsSingle = selectedItem?.report_type === "single";
  const selectedMode = (selectedItem?.exec_mode ?? "position") as "position" | "code" | "dual";
  const dualReviews = selectedItem ? dualVerifyReviews[selectedItem.report_id] ?? [] : [];
  const dualVerifying = selectedItem ? verifyingDualTaskId === selectedItem.report_id : false;
  const dualVerifyDone = !dualVerifying && dualReviews.length > 0 && selectedIsDual;
  const batchVerifying = selectedItem ? verifyingBatchId === selectedItem.report_id : false;

  return (
    <section className="result-page">
      <header className="result-toolbar">
        <div className="result-toolbar-copy">
          <div className="case-hub-kicker">Stage 04 · Report</div>
          <h2>报告中心</h2>
          <p>左侧选报告，右侧直接看步骤回放与验证细节——无需层层展开。</p>
        </div>
        <div className="result-toolbar-actions">
          <div className="result-mode-pills" role="tablist">
            {([
              { id: "all", label: "全部" },
              { id: "dual", label: "双脚本" },
              { id: "position", label: "Position" },
              { id: "code", label: "Code" },
            ] as const).map((mode) => (
              <button
                key={mode.id}
                type="button"
                role="tab"
                className={`result-mode-pill ${execMode === mode.id ? "active" : ""} ${mode.id}`}
                onClick={() => setExecMode(mode.id)}
              >
                {mode.label}
              </button>
            ))}
          </div>
          <label className="result-provider">
            <span>验证模型</span>
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
          <button className="platform-btn" type="button" onClick={() => void loadReports()} disabled={loading}>
            {loading ? "刷新中…" : "刷新"}
          </button>
        </div>
      </header>

      {error && <div className="result-error">{error}</div>}

      <div className="result-split">
        <aside className="result-sidebar">
          <div className="result-sidebar-head">
            <strong>报告列表</strong>
            <span>{reportStats.total} 条</span>
          </div>
          <div className="result-sidebar-list">
            {loading && reportItems.length === 0 && <div className="result-empty">加载中...</div>}
            {!loading && reportItems.length === 0 && (
              <div className="result-empty">暂无报告</div>
            )}
            {reportItems.map((item) => {
              const key = reportKey(item);
              const active = selectedReportKey === key;
              return (
                <button
                  key={key}
                  type="button"
                  className={`result-side-item ${active ? "active" : ""}`}
                  onClick={() => void selectReport(item)}
                >
                  <div className="result-side-item-top">
                    <span className={`result-status ${statusClass(item.status)}`}>
                      {statusLabel(item.status)}
                    </span>
                    <span className="result-side-type">
                      {item.report_type === "dual"
                        ? "Dual"
                        : item.report_type === "batch"
                          ? "Batch"
                          : item.exec_mode}
                    </span>
                  </div>
                  <strong>{reportTitle(item)}</strong>
                  <span className="result-side-meta">
                    {formatDateTime(item.created_at)}
                    {item.report_type === "batch"
                      ? ` · ${item.passed_cases}/${item.total_cases} 通过`
                      : item.serial
                        ? ` · ${item.serial.slice(-8)}`
                        : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <main className="result-detail">
          {!selectedItem && (
            <div className="result-empty">
              <div className="platform-empty-title">选择左侧报告</div>
              <p>选中后右侧会直接展示步骤截图、回放与验证结果。</p>
            </div>
          )}

          {selectedItem && (
            <>
              <div className="result-detail-head">
                <div>
                  <div className="result-detail-kicker">
                    {selectedIsDual ? "Dual Report" : selectedIsBatch ? "Batch Report" : "Single Run"}
                  </div>
                  <h3>{reportTitle(selectedItem)}</h3>
                  <p>
                    {formatDateTime(selectedItem.created_at)} · status {statusLabel(selectedItem.status)}
                    {selectedItem.serial ? ` · ${selectedItem.serial}` : ""}
                    {selectedItem.run_uuid ? ` · run ${selectedItem.run_uuid.slice(0, 8)}…` : ""}
                  </p>
                </div>
                <div className="result-detail-actions">
                  {selectedIsDual && (
                    <button
                      type="button"
                      className="result-verify-btn"
                      disabled={
                        dualVerifying ||
                        (selectedItem.status !== "completed" && selectedItem.status !== "success") ||
                        !selectedProvider ||
                        verifyingBatchId !== null ||
                        verifyingRunId !== null
                      }
                      onClick={() => void handleVerifyDual(selectedItem.report_id)}
                    >
                      {dualVerifying ? "验证中..." : dualVerifyDone ? "已验证" : "双脚本验证"}
                    </button>
                  )}
                  {selectedIsBatch && (selectedMode === "position" || selectedMode === "code") && (
                    <button
                      type="button"
                      className="result-verify-btn"
                      disabled={batchVerifying || selectedItem.completed_cases === 0 || !selectedProvider}
                      onClick={() => void handleVerifyBatch(selectedItem.report_id, selectedMode)}
                    >
                      {batchVerifying ? "验证中..." : "批量验证"}
                    </button>
                  )}
                  {selectedItem.run_uuid && (
                    <Link
                      className="result-verify-btn"
                      to={logsHref(selectedItem.run_uuid, selectedMode)}
                    >
                      日志
                    </Link>
                  )}
                  <Link className="platform-btn" to="/tasks">
                    任务
                  </Link>
                </div>
              </div>

              <div className="result-detail-body">
                {loadingReportId === selectedItem.report_id && !selectedDetail && selectedItem.report_type !== "single" && (
                  <div className="result-empty">加载报告详情...</div>
                )}

                {selectedIsDual && (
                  <DualScriptVerifyPanel
                    reviews={dualReviews}
                    verifyingStepOrder={dualVerifying ? verifyingDualStepOrder : null}
                    active={dualVerifying || dualReviews.length > 0}
                  />
                )}

                {selectedIsBatch &&
                  selectedDetail?.case_results.map((caseItem, index) =>
                    renderCaseResult(caseItem, selectedMode === "dual" ? "position" : (selectedMode as "position" | "code"), {
                      caseOrder: index,
                      showVerify: true,
                    })
                  )}

                {selectedIsDual &&
                  selectedDetail?.case_results.map((caseItem, index) =>
                    renderCaseResult(
                      caseItem,
                      caseItem.exec_mode === "code" ? "code" : "position",
                      {
                        caseOrder: index,
                        showVerify: false,
                        pathLabel: caseItem.path_label ?? (caseItem.exec_mode === "code" ? "Code" : "Position"),
                      }
                    )
                  )}

                {selectedIsSingle && selectedItem.run_uuid && (
                  <>
                    {loadingRunId === selectedItem.run_uuid && !runDetails[selectedItem.run_uuid] && (
                      <div className="result-empty">加载截图与回放数据...</div>
                    )}
                    {runDetails[selectedItem.run_uuid] &&
                      renderCaseResult(
                        {
                          case_id: selectedItem.case_id ?? 0,
                          case_name: selectedItem.case_name ?? "单 Case",
                          status: selectedItem.status,
                          run_uuid: selectedItem.run_uuid,
                          total_steps: runDetails[selectedItem.run_uuid].run.total_steps,
                          passed_steps: runDetails[selectedItem.run_uuid].run.steps.filter(
                            (s) => s.status === "success"
                          ).length,
                          error: runDetails[selectedItem.run_uuid].run.error,
                        },
                        selectedItem.exec_mode === "code" ? "code" : "position",
                        { showVerify: selectedItem.exec_mode === "position" || selectedItem.exec_mode === "code" }
                      )}
                  </>
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </section>
  );
}
