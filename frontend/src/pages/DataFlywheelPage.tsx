import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi } from "../api/agent";
import { flywheelApi } from "../api/flywheel";
import { isApiOfflineError } from "../api/http";
import type {
  FlywheelDataset,
  FlywheelEvalJob,
  FlywheelRagDocument,
  FlywheelTrainingJob,
  TrainingConfig,
} from "../types/flywheel";
import type { ProviderInfo } from "../types/agent";
import "./FlywheelPage.css";

type TabId = "datasets" | "rag" | "training" | "eval";

const DEFAULT_TRAIN_CONFIG: TrainingConfig = {
  base_model: "Qwen2.5-VL-7B-Instruct",
  epochs: 3,
  learning_rate: 0.00002,
  batch_size: 4,
  val_split: 0.1,
  lora_rank: 8,
  warmup_ratio: 0.05,
};

export default function DataFlywheelPage() {
  const [tab, setTab] = useState<TabId>("datasets");
  const [datasets, setDatasets] = useState<FlywheelDataset[]>([]);
  const [ragDocs, setRagDocs] = useState<FlywheelRagDocument[]>([]);
  const [trainingJobs, setTrainingJobs] = useState<FlywheelTrainingJob[]>([]);
  const [evalJobs, setEvalJobs] = useState<FlywheelEvalJob[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<number | null>(null);

  const [datasetName, setDatasetName] = useState("");
  const [datasetType, setDatasetType] = useState("train");
  const [goldenOnly, setGoldenOnly] = useState(true);
  const [selectedDatasetId, setSelectedDatasetId] = useState<number | "">("");

  const [trainName, setTrainName] = useState("");
  const [trainConfig, setTrainConfig] = useState<TrainingConfig>(DEFAULT_TRAIN_CONFIG);

  const [evalName, setEvalName] = useState("");
  const [evalProvider, setEvalProvider] = useState("");
  const [selectedTrainingJobId, setSelectedTrainingJobId] = useState<number | "">("");
  const [expandedEvalUuid, setExpandedEvalUuid] = useState<string | null>(null);

  const [useLlmSummary, setUseLlmSummary] = useState(false);
  const [ragProvider, setRagProvider] = useState("");
  const [lastRagExport, setLastRagExport] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [ds, rag, train, evals, prov] = await Promise.all([
        flywheelApi.listDatasets(),
        flywheelApi.listRag(),
        flywheelApi.listTrainingJobs(),
        flywheelApi.listEvalJobs(),
        agentApi.listProviders(),
      ]);
      setDatasets(ds.items);
      setRagDocs(rag.items);
      setTrainingJobs(train.items);
      setEvalJobs(evals.items);
      const reachable = prov.providers.filter((p) => p.available);
      setProviders(reachable);
      setEvalProvider((cur) => cur || prov.default || reachable[0]?.id || "");
      setRagProvider((cur) => cur || prov.default || reachable[0]?.id || "");
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    }
  }, []);

  useEffect(() => {
    void loadAll();
    pollRef.current = window.setInterval(() => {
      void flywheelApi.listTrainingJobs().then((r) => setTrainingJobs(r.items));
      void flywheelApi.listEvalJobs().then((r) => setEvalJobs(r.items));
    }, 3000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [loadAll]);

  const createDataset = async () => {
    if (!datasetName.trim()) {
      alert("请输入数据集名称");
      return;
    }
    setLoading(true);
    try {
      await flywheelApi.createDataset({
        name: datasetName.trim(),
        dataset_type: datasetType,
        golden_only: goldenOnly,
        cleaning_statuses: goldenOnly ? undefined : ["cleaned", "golden"],
      });
      setDatasetName("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建数据集失败");
    } finally {
      setLoading(false);
    }
  };

  const generateRag = async () => {
    setLoading(true);
    try {
      const resp = await flywheelApi.generateRag({
        dataset_id: selectedDatasetId ? Number(selectedDatasetId) : undefined,
        golden_only: goldenOnly,
        use_llm_summary: useLlmSummary,
        llm_provider: ragProvider || undefined,
      });
      setRagDocs(resp.items);
      setLastRagExport(resp.export_path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成 RAG 失败");
    } finally {
      setLoading(false);
    }
  };

  const createAndStartTraining = async () => {
    if (!trainName.trim() || !selectedDatasetId) {
      alert("请填写任务名并选择数据集");
      return;
    }
    setLoading(true);
    try {
      const job = await flywheelApi.createTrainingJob({
        name: trainName.trim(),
        dataset_id: Number(selectedDatasetId),
        config: trainConfig,
      });
      await flywheelApi.startTrainingJob(job.job_uuid);
      setTrainName("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建训练任务失败");
    } finally {
      setLoading(false);
    }
  };

  const createAndStartEval = async () => {
    if (!evalName.trim() || !selectedDatasetId) {
      alert("请填写评估名并选择 eval 数据集");
      return;
    }
    setLoading(true);
    try {
      const job = await flywheelApi.createEvalJob({
        name: evalName.trim(),
        dataset_id: Number(selectedDatasetId),
        training_job_id: selectedTrainingJobId ? Number(selectedTrainingJobId) : undefined,
        llm_provider: evalProvider || undefined,
        model_ref: selectedTrainingJobId
          ? trainingJobs.find((j) => j.id === Number(selectedTrainingJobId))?.artifact_path ?? undefined
          : undefined,
      });
      await flywheelApi.startEvalJob(job.job_uuid);
      setEvalName("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建评估任务失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flywheel-page">
      <div className="flywheel-tabs">
        {(
          [
            ["datasets", "数据集"],
            ["rag", "黄金 → RAG"],
            ["training", "模型训练"],
            ["eval", "模型评估"],
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

      {tab === "datasets" && (
        <div className="flywheel-panel">
          <h3>创建训练 / 评估数据集</h3>
          <div className="flywheel-toolbar">
            <input
              placeholder="数据集名称"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
            />
            <select value={datasetType} onChange={(e) => setDatasetType(e.target.value)}>
              <option value="train">训练集</option>
              <option value="eval">评估集</option>
              <option value="rag">RAG 集</option>
            </select>
            <label>
              <input type="checkbox" checked={goldenOnly} onChange={(e) => setGoldenOnly(e.target.checked)} />
              仅黄金样本
            </label>
            <button type="button" disabled={loading} onClick={() => void createDataset()}>
              创建数据集
            </button>
          </div>
          <table className="flywheel-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>类型</th>
                <th>样本数</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.id}>
                  <td>{d.id}</td>
                  <td>{d.name}</td>
                  <td>{d.dataset_type}</td>
                  <td>{d.sample_count}</td>
                  <td>{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "rag" && (
        <div className="flywheel-panel">
          <h3>黄金数据转 RAG 文档</h3>
          <div className="flywheel-toolbar">
            <select
              value={selectedDatasetId}
              onChange={(e) => setSelectedDatasetId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">全部黄金样本</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.sample_count})
                </option>
              ))}
            </select>
            <label>
              <input type="checkbox" checked={goldenOnly} onChange={(e) => setGoldenOnly(e.target.checked)} />
              仅黄金
            </label>
            <label>
              <input type="checkbox" checked={useLlmSummary} onChange={(e) => setUseLlmSummary(e.target.checked)} />
              LLM 压缩摘要
            </label>
            <select value={ragProvider} onChange={(e) => setRagProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            <button type="button" disabled={loading} onClick={() => void generateRag()}>
              生成 RAG
            </button>
          </div>
          {lastRagExport && <p className="flywheel-export-path">已导出：{lastRagExport}</p>}
          {ragDocs.map((doc) => (
            <div key={doc.id} className="flywheel-rag-doc">
              <strong>{doc.title}</strong>
              <pre>{doc.content}</pre>
            </div>
          ))}
        </div>
      )}

      {tab === "training" && (
        <div className="flywheel-panel">
          <h3>训练任务（MVP 编排 + 产物导出）</h3>
          <div className="flywheel-toolbar">
            <input placeholder="任务名称" value={trainName} onChange={(e) => setTrainName(e.target.value)} />
            <select
              value={selectedDatasetId}
              onChange={(e) => setSelectedDatasetId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">选择数据集</option>
              {datasets.filter((d) => d.dataset_type === "train").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <button type="button" disabled={loading} onClick={() => void createAndStartTraining()}>
              创建并启动训练
            </button>
          </div>
          <div className="flywheel-config-grid flywheel-form">
            {(
              [
                ["base_model", "基座模型", "text"],
                ["epochs", "Epochs", "number"],
                ["learning_rate", "Learning Rate", "number"],
                ["batch_size", "Batch Size", "number"],
                ["val_split", "验证集比例", "number"],
                ["lora_rank", "LoRA Rank", "number"],
                ["warmup_ratio", "Warmup", "number"],
              ] as const
            ).map(([key, label, type]) => (
              <label key={key}>
                {label}
                <input
                  type={type}
                  value={String(trainConfig[key])}
                  onChange={(e) =>
                    setTrainConfig((prev) => ({
                      ...prev,
                      [key]:
                        type === "number"
                          ? key === "learning_rate"
                            ? parseFloat(e.target.value)
                            : parseInt(e.target.value, 10)
                          : e.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
          {trainingJobs.map((job) => (
            <div key={job.job_uuid} className="flywheel-job-card">
              <header>
                <strong>{job.name}</strong>
                <span>{job.status}</span>
              </header>
              <p className="flywheel-hint">{job.current_stage ?? "等待启动"}</p>
              <div className="flywheel-progress">
                <span style={{ width: `${job.progress_pct}%` }} />
              </div>
              {job.metrics && <pre>{JSON.stringify(job.metrics, null, 2)}</pre>}
              {job.artifact_path && <small>产物：{job.artifact_path}</small>}
              {job.error && <div className="flywheel-error">{job.error}</div>}
            </div>
          ))}
        </div>
      )}

      {tab === "eval" && (
        <div className="flywheel-panel">
          <h3>大模型评估打分</h3>
          <div className="flywheel-toolbar">
            <input placeholder="评估任务名" value={evalName} onChange={(e) => setEvalName(e.target.value)} />
            <select
              value={selectedDatasetId}
              onChange={(e) => setSelectedDatasetId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">选择 eval 数据集</option>
              {datasets.filter((d) => d.dataset_type === "eval" || d.dataset_type === "train").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <select
              value={selectedTrainingJobId}
              onChange={(e) => setSelectedTrainingJobId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">关联训练任务（可选）</option>
              {trainingJobs.filter((j) => j.status === "completed").map((j) => (
                <option key={j.id} value={j.id}>
                  {j.name}
                </option>
              ))}
            </select>
            <select value={evalProvider} onChange={(e) => setEvalProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            <button type="button" disabled={loading} onClick={() => void createAndStartEval()}>
              创建并启动评估
            </button>
          </div>
          {evalJobs.map((job) => (
            <div key={job.job_uuid} className="flywheel-job-card">
              <header>
                <strong>{job.name}</strong>
                <span>{job.status}</span>
              </header>
              <p className="flywheel-hint">{job.current_stage ?? "等待"}</p>
              <div className="flywheel-progress">
                <span style={{ width: `${job.progress_pct}%` }} />
              </div>
              {job.results && (
                <>
                  <pre>{JSON.stringify((job.results as { aggregate?: unknown }).aggregate, null, 2)}</pre>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      setExpandedEvalUuid((cur) => (cur === job.job_uuid ? null : job.job_uuid))
                    }
                  >
                    {expandedEvalUuid === job.job_uuid ? "收起明细" : "查看逐步打分"}
                  </button>
                </>
              )}
              {expandedEvalUuid === job.job_uuid && job.sample_results?.length > 0 && (
                <table className="flywheel-table">
                  <thead>
                    <tr>
                      <th>样本</th>
                      <th>成功匹配</th>
                      <th>目的分</th>
                      <th>综合分</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.sample_results.map((row) => (
                      <tr key={row.sample_id}>
                        <td>
                          {row.source_run_uuid.slice(0, 8)}… #{row.source_step_order + 1}
                        </td>
                        <td>{row.success_match == null ? "-" : row.success_match ? "✓" : "✗"}</td>
                        <td>{row.purpose_score?.toFixed(2) ?? "-"}</td>
                        <td>{row.overall_score?.toFixed(2) ?? "-"}</td>
                        <td>{row.reasoning ?? row.predicted_purpose ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
