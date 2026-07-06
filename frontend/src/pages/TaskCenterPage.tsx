import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tasksApi, type PlatformTask } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import "./PlatformPages.css";

function statusBadge(status: string) {
  const cls =
    status === "completed"
      ? "platform-badge-success"
      : status === "failed"
        ? "platform-badge-failed"
        : status === "running"
          ? "platform-badge-running"
          : "platform-badge-pending";
  return <span className={`platform-badge ${cls}`}>{status}</span>;
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

  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>任务中心</h2>
        <div className="platform-toolbar">
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
          <button className="platform-btn" type="button" onClick={() => void load()}>
            刷新
          </button>
        </div>
      </div>

      {error && <div className="platform-error">{error}</div>}

      <div className="platform-table-wrap">
        <table className="platform-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>Case</th>
              <th>模式</th>
              <th>状态</th>
              <th>进度</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((task) => (
              <tr key={task.task_uuid}>
                <td>{taskTypeLabel(task.task_type)}</td>
                <td>
                  {task.source_case_id ? (
                    <Link className="platform-link-btn" to={`/cases/${task.source_case_id}/edit`}>
                      {task.case_name ?? `#${task.source_case_id}`}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{task.exec_mode ?? "—"}</td>
                <td>{statusBadge(task.status)}</td>
                <td>
                  {task.progress.completed_steps}/{task.progress.total_steps}
                  {task.progress.message ? ` · ${task.progress.message}` : ""}
                </td>
                <td>{new Date(task.created_at).toLocaleString()}</td>
                <td>
                  <div className="platform-actions">
                    {task.detail_path && (
                      <Link className="platform-link-btn" to={task.detail_path}>
                        详情
                      </Link>
                    )}
                    {["running", "pending"].includes(task.status) && (
                      <button className="platform-link-btn" type="button" onClick={() => void handleCancel(task)}>
                        取消
                      </button>
                    )}
                    {task.ref_uuid && (
                      <Link className="platform-link-btn" to={`/logs?run_uuid=${task.ref_uuid}`}>
                        日志
                      </Link>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="platform-empty">暂无任务</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="platform-pagination">共 {total} 条任务</div>
    </div>
  );
}
