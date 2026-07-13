import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { logsApi, type LogEntry } from "../api/platform";
import { isApiOfflineError } from "../api/http";
import { SourceChip } from "../components/OpsPageShell";
import "./PlatformPages.css";
import "./LogCenterPage.css";

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatClock(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function sourceLabel(source: string) {
  const map: Record<string, string> = {
    position: "Position",
    code: "Code",
    script_gen: "Dual 生成",
    monkey: "Monkey",
  };
  return map[source] ?? source;
}

function summarizeDetail(detail: Record<string, unknown> | null): string {
  if (!detail) return "";
  const keys = Object.keys(detail);
  if (keys.length === 0) return "";
  const preview: string[] = [];
  for (const key of keys.slice(0, 4)) {
    const val = detail[key];
    if (val == null) continue;
    if (typeof val === "string") {
      preview.push(`${key}=${val.length > 48 ? `${val.slice(0, 48)}…` : val}`);
    } else if (typeof val === "number" || typeof val === "boolean") {
      preview.push(`${key}=${val}`);
    } else if (Array.isArray(val)) {
      preview.push(`${key}[${val.length}]`);
    } else {
      preview.push(`${key}:{…}`);
    }
  }
  return preview.join(" · ");
}

export default function LogCenterPage() {
  const [searchParams] = useSearchParams();
  const [source, setSource] = useState(searchParams.get("source") ?? "");
  const [runUuid, setRunUuid] = useState(searchParams.get("run_uuid") ?? "");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showRawOnly, setShowRawOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await logsApi.list({
        source: source || undefined,
        run_uuid: runUuid || undefined,
        limit: 300,
      });
      setItems(resp.items);
      setTotal(resp.total);
      setSelectedId((current) => {
        if (current && resp.items.some((i) => i.id === current)) return current;
        return resp.items[0]?.id ?? null;
      });
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

  const filtered = useMemo(() => {
    const key = q.trim().toLowerCase();
    if (!key) return items;
    return items.filter((log) => {
      const hay = `${log.message} ${log.agent_type} ${log.source} ${log.run_uuid ?? ""}`.toLowerCase();
      return hay.includes(key);
    });
  }, [items, q]);

  const selected = filtered.find((i) => i.id === selectedId) ?? filtered[0] ?? null;

  const stats = useMemo(() => {
    const bySource = {
      position: items.filter((i) => i.source === "position").length,
      code: items.filter((i) => i.source === "code").length,
      script_gen: items.filter((i) => i.source === "script_gen").length,
    };
    return { total, ...bySource };
  }, [items, total]);

  return (
    <div className="platform-page platform-page-flush log-page">
      <header className="log-page-toolbar">
        <div>
          <div className="case-hub-kicker">Ops · Log Inspector</div>
          <h2>日志中心</h2>
          <p>高密度时间线 + 右侧详情。默认展示消息与 detail 摘要，选中后看完整 JSON。</p>
        </div>
        <div className="log-page-filters">
          <select className="platform-select" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">全部来源</option>
            <option value="position">Position</option>
            <option value="code">Code</option>
            <option value="script_gen">Dual 生成</option>
            <option value="monkey">Monkey</option>
          </select>
          <input
            className="platform-input"
            placeholder="run_uuid / task_uuid"
            value={runUuid}
            onChange={(e) => setRunUuid(e.target.value)}
          />
          <input
            className="platform-input"
            placeholder="过滤消息 / agent_type…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="platform-btn platform-btn-primary" type="button" onClick={() => void load()}>
            {loading ? "查询中…" : "查询"}
          </button>
        </div>
      </header>

      <div className="log-stat-strip">
        <span>
          共 <strong>{stats.total}</strong> 条
        </span>
        <span className="pos">
          Position <strong>{stats.position}</strong>
        </span>
        <span className="code">
          Code <strong>{stats.code}</strong>
        </span>
        <span className="accent">
          Dual <strong>{stats.script_gen}</strong>
        </span>
        {q && (
          <span>
            过滤后 <strong>{filtered.length}</strong>
          </span>
        )}
      </div>

      {error && <div className="platform-error" style={{ margin: "0 16px 8px" }}>{error}</div>}

      <div className="log-split">
        <div className="log-console">
          <div className="log-console-head">
            <span>时间线</span>
            <span>{filtered.length} rows</span>
          </div>
          <div className="log-console-body">
            {filtered.map((log) => {
              const active = selected?.id === log.id;
              const detailPreview = summarizeDetail(log.detail);
              return (
                <button
                  key={log.id}
                  type="button"
                  className={`log-line ${active ? "active" : ""} source-${log.source}`}
                  onClick={() => setSelectedId(log.id)}
                >
                  <span className="log-line-time">{formatClock(log.created_at)}</span>
                  <SourceChip source={log.source} />
                  <span className="log-line-agent">{log.agent_type}</span>
                  {log.step_order != null && (
                    <span className="log-line-step">S{log.step_order + 1}</span>
                  )}
                  <span className="log-line-msg">{log.message}</span>
                  {detailPreview && <span className="log-line-detail">{detailPreview}</span>}
                </button>
              );
            })}
            {!loading && filtered.length === 0 && (
              <div className="platform-empty">
                <div className="platform-empty-title">暂无日志</div>
                <p>从报告或任务页带上 run_uuid 跳转，可快速定位。</p>
              </div>
            )}
          </div>
        </div>

        <aside className="log-inspector">
          {!selected && (
            <div className="platform-empty">
              <div className="platform-empty-title">选择一条日志</div>
              <p>右侧展示完整字段与 detail JSON。</p>
            </div>
          )}
          {selected && (
            <>
              <div className="log-inspector-head">
                <div>
                  <div className="log-inspector-kicker">{sourceLabel(selected.source)}</div>
                  <h3>{selected.agent_type}</h3>
                  <p>{formatTime(selected.created_at)}</p>
                </div>
                <div className="log-inspector-actions">
                  {selected.run_uuid && selected.source !== "script_gen" && (
                    <Link
                      className="platform-btn"
                      to={`/reports?runId=${encodeURIComponent(selected.run_uuid)}&mode=${selected.source === "code" ? "code" : "position"}`}
                    >
                      打开报告
                    </Link>
                  )}
                  <button
                    className="platform-btn"
                    type="button"
                    onClick={() => setShowRawOnly((v) => !v)}
                  >
                    {showRawOnly ? "字段视图" : "纯 JSON"}
                  </button>
                </div>
              </div>

              <div className="log-inspector-msg">{selected.message}</div>

              {!showRawOnly && (
                <div className="log-field-grid">
                  <div className="log-field">
                    <label>source</label>
                    <span>{selected.source}</span>
                  </div>
                  <div className="log-field">
                    <label>agent_type</label>
                    <span>{selected.agent_type}</span>
                  </div>
                  <div className="log-field">
                    <label>step</label>
                    <span>{selected.step_order != null ? selected.step_order + 1 : "—"}</span>
                  </div>
                  <div className="log-field">
                    <label>run_uuid</label>
                    <span className="mono">{selected.run_uuid ?? "—"}</span>
                  </div>
                  <div className="log-field">
                    <label>session</label>
                    <span className="mono">{selected.session_uuid ?? "—"}</span>
                  </div>
                  <div className="log-field">
                    <label>id</label>
                    <span className="mono">{selected.id}</span>
                  </div>
                </div>
              )}

              <div className="log-inspector-section">
                <div className="log-inspector-section-title">detail</div>
                {selected.detail ? (
                  <pre className="log-json">{JSON.stringify(selected.detail, null, 2)}</pre>
                ) : (
                  <div className="log-inspector-empty">无结构化 detail</div>
                )}
              </div>

              {showRawOnly && (
                <div className="log-inspector-section">
                  <div className="log-inspector-section-title">raw entry</div>
                  <pre className="log-json">{JSON.stringify(selected, null, 2)}</pre>
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
