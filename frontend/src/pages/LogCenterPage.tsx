import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
    case_recording: "录制生成",
  };
  return map[source] ?? source;
}

function entryKey(log: Pick<LogEntry, "source" | "id">) {
  return `${log.source}:${log.id}`;
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

function matchesQuery(log: LogEntry, key: string) {
  if (!key) return true;
  const hay = [
    log.message,
    log.agent_type,
    log.source,
    sourceLabel(log.source),
    log.run_uuid ?? "",
    log.session_uuid ?? "",
    log.step_order != null ? String(log.step_order + 1) : "",
    log.detail ? JSON.stringify(log.detail) : "",
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(key);
}

function valuePreview(value: unknown): string {
  if (value == null) return "null";
  if (typeof value === "string") {
    const oneLine = value.replace(/\s+/g, " ").trim();
    return oneLine.length > 80 ? `${oneLine.slice(0, 80)}…` : oneLine || '""';
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `Array(${value.length})`;
  if (typeof value === "object") return `Object(${Object.keys(value as object).length})`;
  return String(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function LogTreeNode({
  label,
  value,
  depth = 0,
  defaultOpen = false,
}: {
  label: string;
  value: unknown;
  depth?: number;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const complex = isPlainObject(value) || Array.isArray(value);

  if (!complex) {
    const isLongString = typeof value === "string" && value.length > 120;
    if (isLongString) {
      return (
        <div className="log-tree-node" style={{ paddingLeft: depth * 14 }}>
          <button type="button" className="log-tree-row branch" onClick={() => setOpen((v) => !v)}>
            <span className="log-tree-caret">{open ? "▾" : "▸"}</span>
            <span className="log-tree-key">{label}</span>
            <span className="log-tree-val muted">{valuePreview(value)}</span>
          </button>
          {open && <pre className="log-tree-string embedded">{value as string}</pre>}
        </div>
      );
    }
    return (
      <div className="log-tree-node" style={{ paddingLeft: depth * 14 }}>
        <div className="log-tree-row leaf">
          <span className="log-tree-key">{label}</span>
          <span className={`log-tree-val type-${typeof value}`}>{valuePreview(value)}</span>
        </div>
      </div>
    );
  }

  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(value);

  return (
    <div className="log-tree-node" style={{ paddingLeft: depth * 14 }}>
      <button type="button" className="log-tree-row branch" onClick={() => setOpen((v) => !v)}>
        <span className="log-tree-caret">{open ? "▾" : "▸"}</span>
        <span className="log-tree-key">{label}</span>
        <span className="log-tree-val muted">{valuePreview(value)}</span>
      </button>
      {open && (
        <div className="log-tree-children">
          {entries.length === 0 ? (
            <div className="log-tree-empty" style={{ paddingLeft: 14 }}>
              空
            </div>
          ) : (
            entries.map(([childKey, childVal]) => (
              <LogTreeNode
                key={childKey}
                label={Array.isArray(value) ? `[${childKey}]` : childKey}
                value={childVal}
                depth={depth + 1}
                defaultOpen={false}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function LogEntryEmbeddedDetail({ log }: { log: LogEntry }) {
  return (
    <div className="log-embed-detail">
      <div className="log-embed-message">{log.message || "—"}</div>
      <div className="log-field-grid compact">
        <div className="log-field">
          <label>source</label>
          <span>{sourceLabel(log.source)}</span>
        </div>
        <div className="log-field">
          <label>agent_type</label>
          <span>{log.agent_type}</span>
        </div>
        <div className="log-field">
          <label>step</label>
          <span>{log.step_order != null ? log.step_order + 1 : "—"}</span>
        </div>
        <div className="log-field">
          <label>time</label>
          <span className="mono">{formatTime(log.created_at)}</span>
        </div>
        <div className="log-field">
          <label>run_uuid</label>
          <span className="mono">{log.run_uuid ?? "—"}</span>
        </div>
        <div className="log-field">
          <label>session</label>
          <span className="mono">{log.session_uuid ?? "—"}</span>
        </div>
      </div>
      {log.detail ? (
        <div className="log-tree" key={entryKey(log)}>
          {Object.entries(log.detail).map(([key, value]) => (
            <LogTreeNode key={key} label={key} value={value} defaultOpen={false} />
          ))}
        </div>
      ) : (
        <div className="log-inspector-empty">无结构化 detail</div>
      )}
      <details className="log-embed-raw">
        <summary>原始 JSON</summary>
        <pre className="log-json">{JSON.stringify(log, null, 2)}</pre>
      </details>
    </div>
  );
}

function LogDetailView({
  log,
  related,
  onBack,
}: {
  log: LogEntry;
  related: LogEntry[];
  onBack: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(() => entryKey(log));
  const panelRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const timeline = useMemo(() => {
    if (related.length === 0) return [log];
    const map = new Map(related.map((item) => [entryKey(item), item]));
    map.set(entryKey(log), log);
    return Array.from(map.values()).sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
  }, [log, related]);

  useEffect(() => {
    setExpandedKey(entryKey(log));
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  }, [log]);

  useEffect(() => {
    if (!expandedKey) return;
    const panel = panelRefs.current[expandedKey];
    if (!panel) return;
    requestAnimationFrame(() => {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, [expandedKey]);

  const toggleStep = (key: string) => {
    setExpandedKey((current) => (current === key ? null : key));
  };

  return (
    <div className="log-detail-page">
      <header className="log-detail-toolbar">
        <div className="log-detail-toolbar-main">
          <button className="platform-btn" type="button" onClick={onBack}>
            ← 返回列表
          </button>
          <div>
            <div className="log-inspector-kicker">{sourceLabel(log.source)}</div>
            <h2>{log.agent_type}</h2>
            <p>{formatTime(log.created_at)} · 点击步骤行内展开详情</p>
          </div>
        </div>
        <div className="log-inspector-actions">
          {log.run_uuid && log.source !== "script_gen" && log.source !== "case_recording" && (
            <Link
              className="platform-btn"
              to={`/reports?runId=${encodeURIComponent(log.run_uuid)}&mode=${log.source === "code" ? "code" : "position"}`}
            >
              打开报告
            </Link>
          )}
        </div>
      </header>

      <div className="log-detail-body" ref={bodyRef}>
        <section className="log-detail-section">
          <h3 className="log-detail-section-title">当前日志</h3>
          <div className="log-detail-message">{log.message || "—"}</div>
          <div className="log-field-grid" style={{ marginTop: 12 }}>
            <div className="log-field">
              <label>source</label>
              <span>
                {sourceLabel(log.source)} ({log.source})
              </span>
            </div>
            <div className="log-field">
              <label>agent_type</label>
              <span>{log.agent_type}</span>
            </div>
            <div className="log-field">
              <label>step</label>
              <span>{log.step_order != null ? log.step_order + 1 : "—"}</span>
            </div>
            <div className="log-field">
              <label>id</label>
              <span className="mono">{entryKey(log)}</span>
            </div>
            <div className="log-field">
              <label>run_uuid</label>
              <span className="mono">{log.run_uuid ?? "—"}</span>
            </div>
            <div className="log-field">
              <label>session</label>
              <span className="mono">{log.session_uuid ?? "—"}</span>
            </div>
          </div>
        </section>

        <section className="log-detail-section">
          <h3 className="log-detail-section-title">
            步骤时间线 · {timeline.length}
            <span className="log-detail-section-hint">点击展开 / 收起，详情嵌在行下方</span>
          </h3>
          <div className="log-related-list accordion">
            {timeline.map((item) => {
              const key = entryKey(item);
              const open = expandedKey === key;
              const isFocus = key === entryKey(log);
              return (
                <div
                  key={key}
                  className={`log-accordion-item ${open ? "open" : ""} ${isFocus ? "focus" : ""}`}
                  ref={(el) => {
                    panelRefs.current[key] = el;
                  }}
                >
                  <button
                    type="button"
                    className="log-related-item"
                    onClick={() => toggleStep(key)}
                    aria-expanded={open}
                  >
                    <span className="log-tree-caret">{open ? "▾" : "▸"}</span>
                    <span className="log-line-time">{formatClock(item.created_at)}</span>
                    <SourceChip source={item.source} />
                    <span className="log-line-agent">{item.agent_type}</span>
                    {item.step_order != null ? (
                      <span className="log-line-step">S{item.step_order + 1}</span>
                    ) : (
                      <span className="log-line-step muted">—</span>
                    )}
                    <span className="log-line-msg">{item.message}</span>
                  </button>
                  {open && (
                    <div className="log-accordion-panel">
                      <LogEntryEmbeddedDetail log={item} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

export default function LogCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [source, setSource] = useState(searchParams.get("source") ?? "");
  const [runUuid, setRunUuid] = useState(searchParams.get("run_uuid") ?? "");
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [appliedQ, setAppliedQ] = useState(searchParams.get("q") ?? "");
  const [items, setItems] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(
    searchParams.get("log") ? searchParams.get("log") : null
  );

  const load = useCallback(async (opts?: { source?: string; runUuid?: string }) => {
    const nextSource = opts?.source ?? source;
    const nextRunUuid = opts?.runUuid ?? runUuid;
    setLoading(true);
    setError(null);
    try {
      const resp = await logsApi.list({
        source: nextSource || undefined,
        run_uuid: nextRunUuid.trim() || undefined,
        limit: 500,
      });
      setItems(resp.items);
      setTotal(resp.total);
    } catch (err) {
      if (!isApiOfflineError(err)) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [source, runUuid]);

  useEffect(() => {
    void load();
  }, []);

  const syncParams = useCallback(
    (next: { source?: string; runUuid?: string; q?: string; log?: string | null }) => {
      const params = new URLSearchParams();
      const s = next.source ?? source;
      const r = next.runUuid ?? runUuid;
      const query = next.q ?? appliedQ;
      const log = next.log === undefined ? selectedKey : next.log;
      if (s) params.set("source", s);
      if (r.trim()) params.set("run_uuid", r.trim());
      if (query.trim()) params.set("q", query.trim());
      if (log) params.set("log", log);
      setSearchParams(params, { replace: true });
    },
    [source, runUuid, appliedQ, selectedKey, setSearchParams]
  );

  const handleQuery = () => {
    const nextQ = q.trim();
    setAppliedQ(nextQ);
    setSelectedKey(null);
    syncParams({ q: nextQ, log: null });
    void load({ source, runUuid });
  };

  const filtered = useMemo(() => {
    const key = appliedQ.trim().toLowerCase();
    if (!key) return items;
    return items.filter((log) => matchesQuery(log, key));
  }, [items, appliedQ]);

  const selected = useMemo(
    () => (selectedKey ? filtered.find((i) => entryKey(i) === selectedKey) ?? items.find((i) => entryKey(i) === selectedKey) ?? null : null),
    [filtered, items, selectedKey]
  );

  const related = useMemo(() => {
    if (!selected) return [];
    const scope = selected.run_uuid || selected.session_uuid;
    if (!scope) return [];
    return items
      .filter((item) => item.run_uuid === scope || item.session_uuid === scope)
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  }, [items, selected]);

  const stats = useMemo(() => {
    const bySource = {
      position: filtered.filter((i) => i.source === "position").length,
      code: filtered.filter((i) => i.source === "code").length,
      script_gen: filtered.filter((i) => i.source === "script_gen").length,
      case_recording: filtered.filter((i) => i.source === "case_recording").length,
      monkey: filtered.filter((i) => i.source === "monkey").length,
    };
    return { total, shown: filtered.length, ...bySource };
  }, [filtered, total]);

  const openDetail = (log: LogEntry) => {
    const key = entryKey(log);
    setSelectedKey(key);
    syncParams({ log: key });
  };

  const closeDetail = () => {
    setSelectedKey(null);
    syncParams({ log: null });
  };

  if (selected) {
    return (
      <div className="platform-page platform-page-flush log-page">
        <LogDetailView
          log={selected}
          related={related}
          onBack={closeDetail}
        />
      </div>
    );
  }

  return (
    <div className="platform-page platform-page-flush log-page">
      <header className="log-page-toolbar">
        <div>
          <div className="case-hub-kicker">Ops · Log Inspector</div>
          <h2>日志中心</h2>
          <p>按来源 / UUID / 关键词查询。点击任意一条进入全页层级详情。</p>
        </div>
        <div className="log-page-filters">
          <select
            className="platform-select"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setSelectedKey(null);
            }}
          >
            <option value="">全部来源</option>
            <option value="position">Position</option>
            <option value="code">Code</option>
            <option value="script_gen">Dual 生成</option>
            <option value="case_recording">录制生成</option>
            <option value="monkey">Monkey</option>
          </select>
          <input
            className="platform-input"
            placeholder="run_uuid / task_uuid / session"
            value={runUuid}
            onChange={(e) => setRunUuid(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleQuery();
            }}
          />
          <input
            className="platform-input"
            placeholder="过滤消息 / agent_type…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleQuery();
            }}
          />
          <button className="platform-btn platform-btn-primary" type="button" onClick={handleQuery}>
            {loading ? "查询中…" : "查询"}
          </button>
        </div>
      </header>

      <div className="log-stat-strip">
        <span>
          接口 <strong>{stats.total}</strong>
        </span>
        <span>
          列表 <strong>{stats.shown}</strong>
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
        <span className="warn">
          录制 <strong>{stats.case_recording}</strong>
        </span>
        {appliedQ && (
          <span>
            关键词 <strong>{appliedQ}</strong>
          </span>
        )}
      </div>

      {error && <div className="platform-error" style={{ margin: "0 16px 8px" }}>{error}</div>}

      <div className="log-list-panel">
        <div className="log-console-head">
          <span>时间线</span>
          <span>{loading ? "加载中…" : `${filtered.length} rows`}</span>
        </div>
        <div className="log-console-body">
          {filtered.map((log) => {
            const detailPreview = summarizeDetail(log.detail);
            return (
              <button
                key={entryKey(log)}
                type="button"
                className={`log-line source-${log.source}`}
                onClick={() => openDetail(log)}
              >
                <span className="log-line-time">{formatClock(log.created_at)}</span>
                <SourceChip source={log.source} />
                <span className="log-line-agent">{log.agent_type}</span>
                {log.step_order != null ? (
                  <span className="log-line-step">S{log.step_order + 1}</span>
                ) : (
                  <span className="log-line-step muted">—</span>
                )}
                <span className="log-line-msg">{log.message}</span>
                {detailPreview && <span className="log-line-detail">{detailPreview}</span>}
              </button>
            );
          })}
          {!loading && filtered.length === 0 && (
            <div className="platform-empty">
              <div className="platform-empty-title">暂无匹配日志</div>
              <p>调整来源、UUID 或关键词后重新查询。</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
