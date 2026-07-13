import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { casesApi, type CaseListItem } from "../api/platform";
import { api } from "../api/client";
import { isApiOfflineError } from "../api/http";
import { caseStageStatus, WORKFLOW_STAGES } from "../types/workflow";
import "./PlatformPages.css";

const PIPE_LABEL: Record<string, string> = {
  done: "完成",
  active: "进行中",
  failed: "失败",
  todo: "待做",
};

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function nextAction(item: CaseListItem): { label: string; to: string; primary?: boolean } {
  const stages = caseStageStatus(item.script_status, item.last_run_status);
  if (stages.generate === "todo" || stages.generate === "failed" || stages.generate === "active") {
    return { label: "Dual 生成", to: `/agent/generate/${item.id}`, primary: true };
  }
  if (stages.execute === "todo" || stages.execute === "active" || stages.execute === "failed") {
    return { label: "去执行", to: `/agent/execute/${item.id}`, primary: true };
  }
  return { label: "查看报告", to: `/reports`, primary: true };
}

export default function CaseListPage() {
  const [items, setItems] = useState<CaseListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"cards" | "table">("cards");

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

  const stats = useMemo(() => {
    const ready = items.filter((i) => i.script_status === "ready" || i.script_status === "completed").length;
    const ran = items.filter(
      (i) => i.last_run_status === "completed" || i.last_run_status === "success" || i.last_run_status === "failed"
    ).length;
    return { total, ready, ran };
  }, [items, total]);

  return (
    <div className="platform-page">
      <div className="case-hub-hero">
        <div className="case-hub-hero-main">
          <div className="case-hub-kicker">Workflow Hub</div>
          <h2>从自然语言 Case 到双脚本验证</h2>
          <p>
            按「编写 → 生成 → 执行 → 报告」推进。每张 Case 卡片展示当前阶段，下一步操作一目了然。
          </p>
          <div className="platform-toolbar">
            <Link className="platform-btn platform-btn-primary" to="/cases/new">
              新建 Case
            </Link>
            <Link className="platform-btn" to="/cases/record">
              录制生成
            </Link>
            <Link className="platform-btn" to="/agent/execute">
              执行工作台
            </Link>
          </div>
        </div>
        <div className="case-hub-stats">
          <div className="case-hub-stat">
            <div className="case-hub-stat-value">{stats.total}</div>
            <div className="case-hub-stat-label">Case 总数</div>
          </div>
          <div className="case-hub-stat">
            <div className="case-hub-stat-value">{stats.ready}</div>
            <div className="case-hub-stat-label">本页已生成脚本</div>
          </div>
          <div className="case-hub-stat">
            <div className="case-hub-stat-value">{stats.ran}</div>
            <div className="case-hub-stat-label">本页已执行</div>
          </div>
        </div>
      </div>

      <div className="case-hub-section-head">
        <h3>我的 Case</h3>
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
          <button
            className="platform-btn"
            type="button"
            onClick={() => {
              setPage(1);
              setQ(searchInput);
            }}
          >
            搜索
          </button>
          <button
            className={`platform-btn ${view === "cards" ? "platform-btn-primary" : ""}`}
            type="button"
            onClick={() => setView("cards")}
          >
            卡片
          </button>
          <button
            className={`platform-btn ${view === "table" ? "platform-btn-primary" : ""}`}
            type="button"
            onClick={() => setView("table")}
          >
            列表
          </button>
        </div>
      </div>

      {error && <div className="platform-error">{error}</div>}

      {view === "cards" ? (
        <>
          <div className="case-card-grid">
            {items.map((item) => {
              const stages = caseStageStatus(item.script_status, item.last_run_status);
              const next = nextAction(item);
              return (
                <article key={item.id} className="case-card">
                  <div className="case-card-top">
                    <div>
                      <h4 className="case-card-name">{item.name}</h4>
                      <div className="case-card-meta">
                        #{item.id} · {item.step_count} 步 · {formatTime(item.updated_at)}
                      </div>
                    </div>
                  </div>

                  <div className="case-card-pipeline" aria-label="工作流进度">
                    {WORKFLOW_STAGES.map((stage) => {
                      const state = stages[stage.id];
                      return (
                        <div key={stage.id} className={`case-pipe-step ${state}`}>
                          <span className="pipe-label">{stage.short}</span>
                          <span className="pipe-state">{PIPE_LABEL[state]}</span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="case-card-actions">
                    <Link className="platform-btn platform-btn-primary" to={next.to}>
                      {next.label}
                    </Link>
                    <Link className="platform-btn" to={`/cases/${item.id}/edit`}>
                      编辑
                    </Link>
                    <Link className="platform-btn" to={`/agent/generate/${item.id}`}>
                      Dual
                    </Link>
                    <Link className="platform-btn" to={`/agent/execute/${item.id}`}>
                      执行
                    </Link>
                    <button
                      className="platform-link-btn danger"
                      type="button"
                      onClick={() => void handleDelete(item)}
                    >
                      删除
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
          {!loading && items.length === 0 && (
            <div className="platform-empty">
              <div className="platform-empty-title">还没有 Case</div>
              <p>从自然语言描述开始，创建第一个可执行的视觉测试 Case。</p>
              <div style={{ marginTop: 16 }}>
                <Link className="platform-btn platform-btn-primary" to="/cases/new">
                  新建 Case
                </Link>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="platform-table-wrap">
          <table className="platform-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>步骤</th>
                <th>脚本</th>
                <th>最近运行</th>
                <th>更新</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.name}</td>
                  <td>{item.step_count}</td>
                  <td>
                    <span
                      className={`platform-badge ${
                        item.script_status === "ready" || item.script_status === "completed"
                          ? "platform-badge-success"
                          : item.script_status === "failed"
                            ? "platform-badge-failed"
                            : item.script_status === "generating"
                              ? "platform-badge-running"
                              : "platform-badge-pending"
                      }`}
                    >
                      {item.script_status ?? "—"}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`platform-badge ${
                        item.last_run_status === "completed" || item.last_run_status === "success"
                          ? "platform-badge-success"
                          : item.last_run_status === "failed"
                            ? "platform-badge-failed"
                            : item.last_run_status === "running"
                              ? "platform-badge-running"
                              : "platform-badge-pending"
                      }`}
                    >
                      {item.last_run_status ?? "—"}
                    </span>
                  </td>
                  <td>{formatTime(item.updated_at)}</td>
                  <td>
                    <div className="platform-actions">
                      <Link className="platform-link-btn" to={`/cases/${item.id}/edit`}>
                        编辑
                      </Link>
                      <Link className="platform-link-btn" to={`/agent/generate/${item.id}`}>
                        Dual
                      </Link>
                      <Link className="platform-link-btn" to={`/agent/execute/${item.id}`}>
                        执行
                      </Link>
                      <button
                        className="platform-link-btn danger"
                        type="button"
                        onClick={() => void handleDelete(item)}
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="platform-empty">暂无 Case</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

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
