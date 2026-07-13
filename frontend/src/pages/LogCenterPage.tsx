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
      if (looksLikeImagePayload(val)) {
        preview.push(`${key}=[image]`);
      } else {
        preview.push(`${key}=${val.length > 48 ? `${val.slice(0, 48)}…` : val}`);
      }
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

const IMAGE_FIELD_LABELS: Record<string, string> = {
  before_image: "执行前",
  after_image: "执行后",
  before_image_annotated: "标注·执行前",
  after_image_annotated: "标注·执行后",
  screen_image: "屏幕",
  screen_image_url: "处理图",
  display_image: "处理图",
  screenshot: "截图",
  screenshot_url: "截图",
  annotated_screenshot_url: "标注截图",
  annotated_image: "标注图",
  image: "图片",
};

type LogImageRef = {
  key: string;
  label: string;
  src: string;
};

function looksLikeImagePayload(value: string): boolean {
  if (value.startsWith("data:image/")) return true;
  if (/^https?:\/\//i.test(value) && /\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(value)) return true;
  if (value.startsWith("/api/") && /\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(value)) return true;
  if (/^[A-Za-z0-9._-]+\.(png|jpe?g|webp|gif)$/i.test(value)) return true;
  // bare base64 screenshot payloads commonly appear in Dual logs
  if (value.length > 800 && /^[A-Za-z0-9+/=\r\n]+$/.test(value.slice(0, 200))) return true;
  return false;
}

function resolveImageSrc(value: string, sessionUuid?: string | null): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("data:image/")) return trimmed;
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith("/api/")) return trimmed;
  if (/^[A-Za-z0-9._-]+\.(png|jpe?g|webp|gif)$/i.test(trimmed) && sessionUuid) {
    return `/api/case-recording/sessions/${encodeURIComponent(sessionUuid)}/assets/${encodeURIComponent(trimmed)}`;
  }
  if (trimmed.length > 800 && /^[A-Za-z0-9+/=\r\n]+$/.test(trimmed.slice(0, 200))) {
    return `data:image/png;base64,${trimmed.replace(/\s/g, "")}`;
  }
  return null;
}

function imageFieldLabel(key: string): string {
  return IMAGE_FIELD_LABELS[key] ?? key;
}

function extractLogImages(
  detail: Record<string, unknown> | null | undefined,
  sessionUuid?: string | null
): LogImageRef[] {
  if (!detail) return [];
  const found: LogImageRef[] = [];
  const seen = new Set<string>();

  const visit = (node: unknown, path: string) => {
    if (typeof node === "string") {
      if (!looksLikeImagePayload(node)) return;
      const src = resolveImageSrc(node, sessionUuid);
      if (!src || seen.has(src)) return;
      seen.add(src);
      const leaf = path.split(".").pop() || path;
      found.push({ key: path, label: imageFieldLabel(leaf), src });
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    if (isPlainObject(node)) {
      for (const [childKey, childVal] of Object.entries(node)) {
        const nextPath = path ? `${path}.${childKey}` : childKey;
        // skip obvious non-image flags
        if (childKey === "annotated_image" && typeof childVal === "boolean") continue;
        visit(childVal, nextPath);
      }
    }
  };

  visit(detail, "");
  return found;
}

function redactDetailForTree(
  detail: Record<string, unknown>,
  sessionUuid?: string | null
): Record<string, unknown> {
  const walk = (node: unknown): unknown => {
    if (typeof node === "string") {
      if (!looksLikeImagePayload(node)) return node;
      const src = resolveImageSrc(node, sessionUuid);
      return src ? { __log_image__: true, src, preview: valuePreview(node) } : node;
    }
    if (Array.isArray(node)) return node.map(walk);
    if (isPlainObject(node)) {
      const out: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(node)) {
        out[key] = walk(val);
      }
      return out;
    }
    return node;
  };
  return walk(detail) as Record<string, unknown>;
}

function LogImageLightbox({
  src,
  label,
  onClose,
}: {
  src: string;
  label: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="log-lightbox" onClick={onClose} role="presentation">
      <div className="log-lightbox-card" onClick={(event) => event.stopPropagation()} role="dialog">
        <div className="log-lightbox-head">
          <strong>{label}</strong>
          <div className="log-lightbox-actions">
            <a className="platform-btn" href={src} target="_blank" rel="noreferrer">
              新窗口打开
            </a>
            <button className="platform-btn" type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
        <img className="log-lightbox-img" src={src} alt={label} />
      </div>
    </div>
  );
}

function LogImageGallery({
  images,
}: {
  images: LogImageRef[];
}) {
  const [active, setActive] = useState<LogImageRef | null>(null);
  if (images.length === 0) return null;

  return (
    <div className="log-image-gallery">
      <div className="log-image-gallery-title">相关图片 · {images.length}</div>
      <div className="log-image-grid">
        {images.map((image) => (
          <button
            key={`${image.key}:${image.src.slice(0, 48)}`}
            type="button"
            className="log-image-card"
            onClick={() => setActive(image)}
            title={`查看 ${image.label}`}
          >
            <img src={image.src} alt={image.label} loading="lazy" />
            <span>{image.label}</span>
          </button>
        ))}
      </div>
      {active && (
        <LogImageLightbox src={active.src} label={active.label} onClose={() => setActive(null)} />
      )}
    </div>
  );
}

function LogTreeNode({
  label,
  value,
  depth = 0,
  defaultOpen = false,
  onOpenImage,
}: {
  label: string;
  value: unknown;
  depth?: number;
  defaultOpen?: boolean;
  onOpenImage?: (src: string, label: string) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const imageMarker =
    isPlainObject(value) && value.__log_image__ === true && typeof value.src === "string"
      ? (value as { src: string; preview?: string })
      : null;

  if (imageMarker) {
    return (
      <div className="log-tree-node" style={{ paddingLeft: depth * 14 }}>
        <div className="log-tree-row leaf image">
          <span className="log-tree-key">{label}</span>
          <button
            type="button"
            className="log-tree-image-link"
            onClick={() => onOpenImage?.(imageMarker.src, imageFieldLabel(label))}
          >
            查看图片
          </button>
        </div>
      </div>
    );
  }

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
                onOpenImage={onOpenImage}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function LogEntryEmbeddedDetail({ log }: { log: LogEntry }) {
  const images = useMemo(
    () => extractLogImages(log.detail, log.session_uuid),
    [log.detail, log.session_uuid]
  );
  const treeDetail = useMemo(
    () => (log.detail ? redactDetailForTree(log.detail, log.session_uuid) : null),
    [log.detail, log.session_uuid]
  );
  const [lightbox, setLightbox] = useState<{ src: string; label: string } | null>(null);

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

      <LogImageGallery images={images} />

      {treeDetail ? (
        <div className="log-tree" key={entryKey(log)}>
          {Object.entries(treeDetail).map(([key, value]) => (
            <LogTreeNode
              key={key}
              label={key}
              value={value}
              defaultOpen={false}
              onOpenImage={(src, label) => setLightbox({ src, label })}
            />
          ))}
        </div>
      ) : (
        <div className="log-inspector-empty">无结构化 detail</div>
      )}
      <details className="log-embed-raw">
        <summary>原始 JSON（图片字段已折叠为链接提示）</summary>
        <pre className="log-json">
          {JSON.stringify(
            treeDetail
              ? Object.fromEntries(
                  Object.entries(treeDetail).map(([key, value]) => {
                    if (isPlainObject(value) && value.__log_image__) {
                      return [key, `[image] ${imageFieldLabel(key)}`];
                    }
                    return [key, value];
                  })
                )
              : log,
            null,
            2
          )}
        </pre>
      </details>
      {lightbox && (
        <LogImageLightbox
          src={lightbox.src}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      )}
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
