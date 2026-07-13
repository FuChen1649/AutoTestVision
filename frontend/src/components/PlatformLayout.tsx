import { useState } from "react";
import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { isNavActive, NAV_GROUPS } from "../types/navigation";
import { navIcon, resolveWorkflowStage } from "../types/workflow";
import WorkflowRail from "./WorkflowRail";
import "./PlatformLayout.css";

function breadcrumbLabel(pathname: string): string {
  if (pathname === "/cases" || pathname.startsWith("/cases/")) {
    if (pathname === "/cases/new") return "新建 Case";
    if (pathname.match(/^\/cases\/\d+\/edit$/)) return "编辑 Case";
    return "Case 管理";
  }
  if (pathname.startsWith("/agent/generate")) return "执行工作台 · Dual";
  if (pathname.startsWith("/agent/execute")) return "执行工作台";
  if (pathname === "/tasks") return "任务中心";
  if (pathname === "/batch") return "跑批管理";
  if (pathname === "/reports") return "报告中心";
  if (pathname === "/logs") return "日志中心";
  if (pathname === "/devices") return "设备管理";
  if (pathname === "/resources") return "资源依赖";
  if (pathname === "/monkey") return "AgentMonkeyTest";
  if (pathname === "/data/cleaning") return "数据清洗";
  if (pathname === "/data/flywheel") return "数据飞轮";
  return "AutoTestVision";
}

function caseIdFromPath(pathname: string, params: Record<string, string | undefined>): number | null {
  if (params.caseId) {
    const n = Number(params.caseId);
    return Number.isFinite(n) ? n : null;
  }
  const m = pathname.match(/\/(?:cases|agent\/generate|agent\/execute)\/(\d+)/);
  return m ? Number(m[1]) : null;
}

export default function PlatformLayout() {
  const location = useLocation();
  const params = useParams();
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const stage = resolveWorkflowStage(location.pathname);
  const caseId = caseIdFromPath(location.pathname, params);

  return (
    <div className={`platform ${navCollapsed ? "platform-nav-collapsed" : ""}`}>
      {mobileNavOpen && (
        <button
          className="platform-nav-backdrop"
          type="button"
          aria-label="关闭导航"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <aside className={mobileNavOpen ? "platform-sidebar platform-sidebar-open" : "platform-sidebar"}>
        <div className="platform-sidebar-header">
          <Link to="/cases" className="platform-brand" onClick={() => setMobileNavOpen(false)}>
            <span className="platform-brand-mark">AV</span>
            <span className="platform-brand-text">
              <span className="platform-brand-title">AutoTestVision</span>
              <span className="platform-brand-sub">Vision QA Platform</span>
            </span>
          </Link>
          <button
            className="platform-collapse-btn"
            type="button"
            aria-label={navCollapsed ? "展开导航" : "收起导航"}
            onClick={() => setNavCollapsed((v) => !v)}
          >
            {navCollapsed ? "»" : "«"}
          </button>
        </div>

        <nav className="platform-nav">
          {NAV_GROUPS.map((group) => (
            <div key={group.id} className="platform-nav-group">
              {!navCollapsed && <div className="platform-nav-group-title">{group.title}</div>}
              {group.items.map((item) => {
                const active = isNavActive(location.pathname, item);
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={active ? "platform-nav-item active" : "platform-nav-item"}
                    title={navCollapsed ? item.label : undefined}
                    onClick={() => setMobileNavOpen(false)}
                  >
                    <span className="platform-nav-item-icon" aria-hidden>
                      {navIcon(item)}
                    </span>
                    <span className="platform-nav-item-body">
                      <span className="platform-nav-item-label">{item.label}</span>
                      {!navCollapsed && (
                        <span className="platform-nav-item-desc">{item.description}</span>
                      )}
                    </span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {!navCollapsed && (
          <div className="platform-sidebar-footer">
            <div className="platform-sidebar-hint">
              工作流：编写 → 生成 → 执行 → 报告
            </div>
          </div>
        )}
      </aside>

      <div className="platform-main">
        <header className="platform-header">
          <div className="platform-header-left">
            <button
              className="platform-menu-btn"
              type="button"
              aria-label="打开导航"
              onClick={() => setMobileNavOpen(true)}
            >
              ☰
            </button>
            <div className="platform-header-titles">
              <h1>{breadcrumbLabel(location.pathname)}</h1>
              <p className="platform-breadcrumb">{location.pathname}</p>
            </div>
          </div>
          <div className="platform-header-right">
            {stage && <WorkflowRail activeId={stage.id} caseId={caseId} compact />}
          </div>
        </header>
        <div className="platform-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
