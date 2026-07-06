import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { casesApi, type CaseListItem } from "../api/platform";
import { api } from "../api/client";
import { isApiOfflineError } from "../api/http";
import "./PlatformPages.css";

function statusBadge(status: string | null) {
  if (!status) return <span className="platform-badge platform-badge-pending">—</span>;
  const cls =
    status === "completed" || status === "ready"
      ? "platform-badge-success"
      : status === "failed"
        ? "platform-badge-failed"
        : status === "running" || status === "generating"
          ? "platform-badge-running"
          : "platform-badge-pending";
  return <span className={`platform-badge ${cls}`}>{status}</span>;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}

export default function CaseListPage() {
  const [items, setItems] = useState<CaseListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await casesApi.list({ q: q || undefined, page, size: 20 });
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    } finally {
      setLoading(false);
    }
  }, [page, q]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (item: CaseListItem) => {
    if (!window.confirm(`确定删除 Case「${item.name}」？`)) return;
    try {
      await api.deleteCase(item.id);
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>Case 管理</h2>
        <div className="platform-toolbar">
          <input
            className="platform-input"
            placeholder="搜索 Case 名称…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setPage(1);
                setQ(searchInput);
              }
            }}
          />
          <button className="platform-btn" type="button" onClick={() => { setPage(1); setQ(searchInput); }}>
            搜索
          </button>
          <Link className="platform-btn platform-btn-primary" to="/cases/new">
            新建 Case
          </Link>
        </div>
      </div>

      {error && <div className="platform-error">{error}</div>}

      <div className="platform-table-wrap">
        <table className="platform-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>步骤数</th>
              <th>脚本状态</th>
              <th>最近运行</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.name}</td>
                <td>{item.step_count}</td>
                <td>{statusBadge(item.script_status)}</td>
                <td>{statusBadge(item.last_run_status)}</td>
                <td>{formatTime(item.updated_at)}</td>
                <td>
                  <div className="platform-actions">
                    <Link className="platform-link-btn" to={`/cases/${item.id}/edit`}>
                      编辑
                    </Link>
                    <Link className="platform-link-btn" to={`/agent/generate/${item.id}`}>
                      生成脚本
                    </Link>
                    <Link className="platform-link-btn" to={`/agent/execute/${item.id}`}>
                      执行
                    </Link>
                    <button className="platform-link-btn" type="button" onClick={() => void handleDelete(item)}>
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="platform-empty">暂无 Case，点击「新建 Case」开始</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="platform-pagination">
        <button className="platform-btn" type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          上一页
        </button>
        <span>
          第 {page} 页 · 共 {total} 条
        </span>
        <button
          className="platform-btn"
          type="button"
          disabled={page * 20 >= total}
          onClick={() => setPage((p) => p + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
