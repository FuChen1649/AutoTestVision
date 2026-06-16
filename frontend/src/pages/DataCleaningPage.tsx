import { useCallback, useEffect, useState } from "react";
import { flywheelApi } from "../api/flywheel";
import { isApiOfflineError } from "../api/http";
import type { CleaningStatus, FlywheelSample, FlywheelStats } from "../types/flywheel";
import "./FlywheelPage.css";

type TabId = "overview" | "cleaning" | "annotation";

const STATUS_LABELS: Record<CleaningStatus, string> = {
  raw: "原始",
  cleaned: "已清洗",
  rejected: "已拒绝",
  golden: "黄金",
};

function badgeClass(status: CleaningStatus) {
  return `flywheel-badge ${status}`;
}

export default function DataCleaningPage() {
  const [tab, setTab] = useState<TabId>("overview");
  const [stats, setStats] = useState<FlywheelStats | null>(null);
  const [samples, setSamples] = useState<FlywheelSample[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSample, setSelectedSample] = useState<FlywheelSample | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncLimit, setSyncLimit] = useState(100);
  const [minQuality, setMinQuality] = useState(0.5);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const [labelSuccess, setLabelSuccess] = useState<string>("");
  const [labelPurpose, setLabelPurpose] = useState("");
  const [labelAction, setLabelAction] = useState("tap");
  const [labelNotes, setLabelNotes] = useState("");
  const [isGolden, setIsGolden] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      setStats(await flywheelApi.getStats());
    } catch (err) {
      if (!isApiOfflineError(err)) console.warn(err);
    }
  }, []);

  const loadSamples = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await flywheelApi.listSamples({
        cleaning_status: filterStatus || undefined,
        limit: 50,
        include_images: tab === "annotation",
      });
      setSamples(resp.items);
      setTotal(resp.total);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载样本失败");
      }
    } finally {
      setLoading(false);
    }
  }, [filterStatus, tab]);

  useEffect(() => {
    void loadStats();
    void loadSamples();
  }, [loadStats, loadSamples]);

  const handleSync = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await flywheelApi.syncSamples({ limit_runs: syncLimit });
      setError(null);
      alert(`同步完成：共 ${result.synced} 条，新建 ${result.created}，更新 ${result.updated}`);
      await loadStats();
      await loadSamples();
    } catch (err) {
      setError(err instanceof Error ? err.message : "同步失败");
    } finally {
      setLoading(false);
    }
  };

  const handleAutoClean = async () => {
    setLoading(true);
    try {
      const result = await flywheelApi.autoClean({
        min_quality_score: minQuality,
        require_both_images: true,
        dedupe: true,
      });
      alert(
        `自动清洗完成：通过 ${result.marked_cleaned}，拒绝 ${result.marked_rejected}，去重 ${result.deduped}`
      );
      await loadStats();
      await loadSamples();
    } catch (err) {
      setError(err instanceof Error ? err.message : "自动清洗失败");
    } finally {
      setLoading(false);
    }
  };

  const openSample = async (sample: FlywheelSample) => {
    setSelectedId(sample.id);
    try {
      const detail = await flywheelApi.getSample(sample.id);
      setSelectedSample(detail);
      const ann = detail.annotation;
      setLabelSuccess(
        ann?.label_success === true ? "true" : ann?.label_success === false ? "false" : ""
      );
      setLabelPurpose(ann?.label_purpose ?? detail.auto_purpose ?? detail.description);
      setLabelAction(ann?.label_action ?? "tap");
      setLabelNotes(ann?.notes ?? "");
      setIsGolden(ann?.is_golden ?? false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载样本详情失败");
    }
  };

  const saveAnnotation = async () => {
    if (!selectedId) return;
    setLoading(true);
    try {
      await flywheelApi.annotateSample(selectedId, {
        label_success: labelSuccess === "" ? null : labelSuccess === "true",
        label_purpose: labelPurpose,
        label_action: labelAction,
        notes: labelNotes,
        is_golden: isGolden,
      });
      await loadStats();
      await loadSamples();
      if (selectedSample) await openSample(selectedSample);
      alert("标注已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存标注失败");
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const bulkMark = async (status: CleaningStatus) => {
    if (!selectedIds.length) {
      alert("请先勾选样本");
      return;
    }
    await flywheelApi.bulkClean({ sample_ids: selectedIds, cleaning_status: status });
    setSelectedIds([]);
    await loadStats();
    await loadSamples();
  };

  return (
    <div className="flywheel-page">
      <div className="flywheel-tabs">
        {(
          [
            ["overview", "概览 & 同步"],
            ["cleaning", "数据清洗"],
            ["annotation", "人工标注"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`flywheel-tab ${tab === id ? "active" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <div className="flywheel-error">{error}</div>}

      {stats && (
        <div className="flywheel-stats">
          {[
            ["总样本", stats.total_samples],
            ["原始", stats.raw_count],
            ["已清洗", stats.cleaned_count],
            ["已拒绝", stats.rejected_count],
            ["黄金", stats.golden_count],
            ["已标注", stats.annotated_count],
            ["双图齐全", stats.with_images_count],
          ].map(([label, value]) => (
            <div key={String(label)} className="flywheel-stat-card">
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      )}

      {tab === "overview" && (
        <div className="flywheel-panel">
          <h3>从 Agent 执行结果同步样本</h3>
          <div className="flywheel-toolbar">
            <label>
              最近 run 数
              <input
                type="number"
                min={1}
                max={500}
                value={syncLimit}
                onChange={(e) => setSyncLimit(Number(e.target.value))}
              />
            </label>
            <button type="button" disabled={loading} onClick={() => void handleSync()}>
              同步样本
            </button>
            <button type="button" className="secondary" disabled={loading} onClick={() => void loadStats()}>
              刷新统计
            </button>
          </div>
          <p className="flywheel-hint">
            从 `agent_run_steps` 抽取步骤描述、验证结果、目的分析与截图标记，作为飞轮训练原料。
          </p>
        </div>
      )}

      {tab === "cleaning" && (
        <div className="flywheel-panel">
          <h3>自动 / 批量清洗</h3>
          <div className="flywheel-toolbar">
            <label>
              最低质量分
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={minQuality}
                onChange={(e) => setMinQuality(Number(e.target.value))}
              />
            </label>
            <button type="button" disabled={loading} onClick={() => void handleAutoClean()}>
              运行自动清洗
            </button>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="raw">原始</option>
              <option value="cleaned">已清洗</option>
              <option value="rejected">已拒绝</option>
              <option value="golden">黄金</option>
            </select>
            <button type="button" className="secondary" onClick={() => void bulkMark("cleaned")}>
              批量标记已清洗
            </button>
            <button type="button" className="secondary" onClick={() => void bulkMark("rejected")}>
              批量拒绝
            </button>
          </div>
          <div className="flywheel-sample-list">
            {samples.map((sample) => (
              <div key={sample.id} className="flywheel-sample-item">
                <label className="flywheel-sample-check">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(sample.id)}
                    onChange={() => toggleSelect(sample.id)}
                  />
                  <span>
                    <span className={badgeClass(sample.cleaning_status)}>{STATUS_LABELS[sample.cleaning_status]}</span>
                    <strong>{sample.case_name}</strong> · 步骤 {sample.source_step_order + 1}
                    <br />
                    <small>{sample.description}</small>
                    <br />
                    <small>
                      质量 {sample.quality_score.toFixed(2)}
                      {sample.exclude_reason ? ` · ${sample.exclude_reason}` : ""}
                    </small>
                  </span>
                </label>
              </div>
            ))}
            {!samples.length && !loading && <p className="flywheel-empty-list">暂无样本，请先在概览页同步。</p>}
          </div>
          <p className="flywheel-count">共 {total} 条</p>
        </div>
      )}

      {tab === "annotation" && (
        <div className="flywheel-layout">
          <div className="flywheel-sample-list">
            {samples.map((sample) => (
              <div
                key={sample.id}
                className={`flywheel-sample-item ${selectedId === sample.id ? "active" : ""}`}
                onClick={() => void openSample(sample)}
              >
                <span className={badgeClass(sample.cleaning_status)}>{STATUS_LABELS[sample.cleaning_status]}</span>
                {sample.annotation?.is_golden && <span className="flywheel-badge golden">★</span>}
                <strong>{sample.case_name}</strong>
                <br />
                <small>{sample.description}</small>
              </div>
            ))}
          </div>

          <div className="flywheel-detail flywheel-panel">
            {!selectedSample ? (
              <p>请选择左侧样本进行人工标注</p>
            ) : (
              <>
                <h3>
                  {selectedSample.case_name} · 步骤 {selectedSample.source_step_order + 1}
                </h3>
                <p className="flywheel-hint">{selectedSample.description}</p>
                <div className="flywheel-images">
                  <div>
                    <small>执行前</small>
                    {selectedSample.before_image ? (
                      <img src={selectedSample.before_image} alt="before" />
                    ) : (
                      <div className="flywheel-empty-image">无截图</div>
                    )}
                  </div>
                  <div>
                    <small>执行后</small>
                    {selectedSample.after_image ? (
                      <img src={selectedSample.after_image} alt="after" />
                    ) : (
                      <div className="flywheel-empty-image">无截图</div>
                    )}
                  </div>
                </div>
                <div className="flywheel-form">
                  <label>
                    是否执行成功
                    <select value={labelSuccess} onChange={(e) => setLabelSuccess(e.target.value)}>
                      <option value="">未标注</option>
                      <option value="true">成功</option>
                      <option value="false">失败</option>
                    </select>
                  </label>
                  <label>
                    执行目的（黄金标签）
                    <textarea value={labelPurpose} onChange={(e) => setLabelPurpose(e.target.value)} />
                  </label>
                  <label>
                    操作类型
                    <select value={labelAction} onChange={(e) => setLabelAction(e.target.value)}>
                      <option value="tap">tap</option>
                      <option value="swipe">swipe</option>
                      <option value="long_press">long_press</option>
                      <option value="skip">skip</option>
                    </select>
                  </label>
                  <label>
                    备注
                    <textarea value={labelNotes} onChange={(e) => setLabelNotes(e.target.value)} />
                  </label>
                  <label>
                    <input type="checkbox" checked={isGolden} onChange={(e) => setIsGolden(e.target.checked)} />
                    标记为黄金数据
                  </label>
                </div>
                <div className="flywheel-toolbar">
                  <button type="button" disabled={loading} onClick={() => void saveAnnotation()}>
                    保存标注
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      void flywheelApi.cleanSample(selectedId!, { cleaning_status: "cleaned" }).then(loadSamples)
                    }
                  >
                    标记已清洗
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
