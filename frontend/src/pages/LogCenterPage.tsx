import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { logsApi, type LogEntry } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import "./PlatformPages.css";

export default function LogCenterPage() {
  const [searchParams] = useSearchParams();
  const [source, setSource] = useState(searchParams.get("source") ?? "");
  const [runUuid, setRunUuid] = useState(searchParams.get("run_uuid") ?? "");
  const [items, setItems] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await logsApi.list({
        source: source || undefined,
        run_uuid: runUuid || undefined,
        limit: 200,
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
  }, [source, runUuid]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>日志中心</h2>
        <div className="platform-toolbar">
          <select className="platform-select" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">全部来源</option>
            <option value="position">Position 执行</option>
            <option value="code">Code 执行</option>
            <option value="script_gen">双脚本生成</option>
            <option value="monkey">Monkey</option>
          </select>
          <input
            className="platform-input"
            placeholder="run_uuid / task_uuid"
            value={runUuid}
            onChange={(e) => setRunUuid(e.target.value)}
          />
          <button className="platform-btn" type="button" onClick={() => void load()}>
            查询
          </button>
        </div>
      </div>

      {error && <div className="platform-error">{error}</div>}

      <div className="platform-table-wrap">
        <table className="platform-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>来源</th>
              <th>类型</th>
              <th>步骤</th>
              <th>消息</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((log) => (
              <Fragment key={log.id}>
                <tr>
                  <td>{new Date(log.created_at).toLocaleString()}</td>
                  <td>{log.source}</td>
                  <td>{log.agent_type}</td>
                  <td>{log.step_order ?? "—"}</td>
                  <td>{log.message}</td>
                  <td>
                    {log.detail && (
                      <button className="platform-link-btn" type="button" onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}>
                        详情
                      </button>
                    )}
                    {log.run_uuid && log.source !== "script_gen" && (
                      <Link
                        className="platform-link-btn"
                        to={`/reports?runId=${encodeURIComponent(log.run_uuid)}&mode=${log.source === "code" ? "code" : "position"}`}
                        style={{ marginLeft: 8 }}
                      >
                        报告
                      </Link>
                    )}
                  </td>
                </tr>
                {expandedId === log.id && log.detail && (
                  <tr>
                    <td colSpan={6}>
                      <pre className="platform-pre">{JSON.stringify(log.detail, null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6}>
                  <div className="platform-empty">暂无日志</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="platform-pagination">共 {total} 条</div>
    </div>
  );
}
