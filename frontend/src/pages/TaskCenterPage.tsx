import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { tasksApi, type PlatformTask } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import OpsPageShell, { ModeChip, ProgressBar } from "../components/OpsPageShell";
import "../pages/PlatformPages.css";

function statusBadge(status: string) {
  const cls =
    status === "completed"
      ? "platform-badge-success"
      : status === "failed"
        ? "platform-badge-failed"
        : status === "running"
          ? "platform-badge-running"
          : "platform-badge-pending";
  const label =
    status === "completed"
      ? "已完成"
      : status === "failed"
        ? "失败"
        : status === "running"
          ? "执行中"
          : status === "cancelled"
            ? "已取消"
            : status === "pending"
              ? "排队中"
              : status;
  return <span className={`platform-badge ${cls}`}>{label}</span>;
}

function taskTypeLabel(type: string) {
  const map: Record<string, string> = {
    script_generation: "脚本生成",
    run: "单次执行",
    batch: "批量执行",
    verify: "结果验证",
  };
  return map[type] ?? type;
}

function taskTone(status: string) {
  if (status === "running") return "running";
  if (status === "failed") return "failed";
  return "";
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function TaskCenterPage() {
  const [items, setItems] = useState<PlatformTask[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await tasksApi.list({
        status: statusFilter || undefined,
        task_type: typeFilter || undefined,
        limit: 50,
      });
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    } finally {
      setLoading(false);
    }
  }, [statusFilter, typeFilter]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const handleCancel = async (task: PlatformTask) => {
    if (!window.confirm(`确定取消任务 ${task.task_uuid.slice(0, 8)}…？`)) return;
    try {
      await tasksApi.cancel(task.task_uuid);
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消失败");
    }
  };

  const stats = useMemo(() => {
    const running = items.filter((t) => t.status === "running" || t.status === "pending").length;
    const completed = items.filter((t) => t.status === "completed").length;
    const failed = items.filter((t) => t.status === "failed").length;
    return { running, completed, failed, total };
  }, [items, total]);

  return (
    <OpsPageShell
      kicker="Ops · Task Monitor"
      title="任务中心"
      lead="统一查看脚本生成、单次执行与跑批任务。每 5 秒自动刷新，可跳转详情、日志或取消进行中的任务。"
      stats={[
        { label: "任务总数", value: stats.total },
        { label: "进行中", value: stats.running, tone: "info" },
        { label: "已完成", value: stats.completed, tone: "ok" },
        { label: "失败", value: stats.failed, tone: "danger" },
      ]}
      actions={
        <button className="platform-btn" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "刷新中…" : "立即刷新"}
        </button>
      }
      filters={
        <>
          <select
            className="platform-select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="">全部类型</option>
            <option value="script_generation">脚本生成</option>
            <option value="run">单次执行</option>
            <option value="batch">批量执行</option>
          </select>
          <select
            className="platform-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">全部状态</option>
            <option value="running">执行中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
          </select>
          <Link className="platform-btn" to="/batch">
            去跑批
          </Link>
          <Link className="platform-btn" to="/reports">
            报告中心
          </Link>
        </>
      }
    >
      {error && <div className="platform-error">{error}</div>}

      <div className="ops-card-list">
        {items.map((task) => (
          <article key={task.task_uuid} className={`ops-task-card ${taskTone(task.status)}`}>
            <div className="ops-task-main">
              <div className="ops-task-top">
                <h3 className="ops-task-title">{taskTypeLabel(task.task_type)}</h3>
                {statusBadge(task.status)}
                <ModeChip mode={task.exec_mode} />
              </div>
              <div className="ops-task-meta">
                {task.task_uuid.slice(0, 8)}… · {formatTime(task.created_at)}
                {task.serial ? ` · ${task.serial}` : ""}
              </div>
              <div className="ops-task-meta" style={{ marginTop: 6 }}>
                Case：
                {task.source_case_id ? (
                  <Link className="platform-link-btn" to={`/cases/${task.source_case_id}/edit`}>
                    {task.case_name ?? `#${task.source_case_id}`}
                  </Link>
                ) : (
                  "—"
                )}
              </div>
              {task.progress.message && <div className="ops-task-msg">{task.progress.message}</div>}
              {task.error && (
                <div className="ops-task-msg" style={{ color: "var(--danger)" }}>
                  {task.error}
                </div>
              )}
            </div>
            <div className="ops-task-side">
              <ProgressBar
                completed={task.progress.completed_steps}
                total={task.progress.total_steps}
                tone={
                  task.status === "failed"
                    ? "danger"
                    : task.exec_mode === "code"
                      ? "code"
                      : task.exec_mode === "position"
                        ? "pos"
                        : "accent"
                }
              />
              <div className="ops-task-actions">
                {task.detail_path && (
                  <Link className="platform-btn" to={task.detail_path}>
                    详情
                  </Link>
                )}
                {task.ref_uuid && (
                  <Link className="platform-btn" to={`/logs?run_uuid=${task.ref_uuid}`}>
                    日志
                  </Link>
                )}
                {["running", "pending"].includes(task.status) && (
                  <button
                    className="platform-link-btn danger"
                    type="button"
                    onClick={() => void handleCancel(task)}
                  >
                    取消
                  </button>
                )}
              </div>
            </div>
          </article>
        ))}
        {!loading && items.length === 0 && (
          <div className="platform-empty">
            <div className="platform-empty-title">暂无任务</div>
            <p>从双脚本生成、执行工作台或跑批启动后，任务会出现在这里。</p>
          </div>
        )}
      </div>
    </OpsPageShell>
  );
}
