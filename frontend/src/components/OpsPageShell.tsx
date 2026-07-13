import type { ReactNode } from "react";
import "./OpsPages.css";

interface StatItem {
  label: string;
  value: string | number;
  tone?: "default" | "ok" | "warn" | "danger" | "info" | "pos" | "code" | "accent";
}

interface OpsPageShellProps {
  kicker: string;
  title: string;
  lead: string;
  stats?: StatItem[];
  actions?: ReactNode;
  filters?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}

export default function OpsPageShell({
  kicker,
  title,
  lead,
  stats,
  actions,
  filters,
  children,
  flush,
}: OpsPageShellProps) {
  return (
    <div className={`platform-page ops-page ${flush ? "platform-page-flush ops-page-flush" : ""}`}>
      <header className="ops-hero">
        <div className="ops-hero-main">
          <div className="ops-kicker">{kicker}</div>
          <div className="ops-hero-title-row">
            <h2>{title}</h2>
            {actions && <div className="ops-hero-actions">{actions}</div>}
          </div>
          <p className="ops-lead">{lead}</p>
          {filters && <div className="ops-filters">{filters}</div>}
        </div>
        {stats && stats.length > 0 && (
          <div className="ops-stats">
            {stats.map((s) => (
              <div key={s.label} className={`ops-stat ${s.tone ?? "default"}`}>
                <div className="ops-stat-value">{s.value}</div>
                <div className="ops-stat-label">{s.label}</div>
              </div>
            ))}
          </div>
        )}
      </header>
      <div className="ops-body">{children}</div>
    </div>
  );
}

export function ProgressBar({
  completed,
  total,
  tone = "accent",
}: {
  completed: number;
  total: number;
  tone?: "accent" | "pos" | "code" | "ok" | "danger";
}) {
  const pct = total > 0 ? Math.min(100, Math.round((completed / Math.max(total, 1)) * 100)) : 0;
  return (
    <div className="ops-progress" title={`${completed}/${total}`}>
      <div className="ops-progress-track">
        <div className={`ops-progress-fill ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="ops-progress-text">
        {completed}/{total}
        {total > 0 ? ` · ${pct}%` : ""}
      </span>
    </div>
  );
}

export function ModeChip({ mode }: { mode: string | null | undefined }) {
  if (!mode) return <span className="ops-chip muted">—</span>;
  const tone = mode === "code" ? "code" : mode === "dual" ? "accent" : mode === "position" ? "pos" : "muted";
  return <span className={`ops-chip ${tone}`}>{mode}</span>;
}

export function SourceChip({ source }: { source: string }) {
  const map: Record<string, string> = {
    position: "pos",
    code: "code",
    script_gen: "accent",
    monkey: "warn",
    case_recording: "warn",
  };
  const label =
    source === "case_recording" ? "recording" : source === "script_gen" ? "dual" : source;
  return <span className={`ops-chip ${map[source] ?? "muted"}`}>{label}</span>;
}
