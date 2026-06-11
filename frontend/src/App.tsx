import { useState } from "react";
import AppNav from "./components/AppNav";
import AgentTestPage from "./pages/AgentTestPage";
import CaseBuilderPage from "./pages/CaseBuilderPage";
import ResultPage from "./pages/ResultPage";
import { NAV_ITEMS, type AppPageId } from "./types/navigation";
import "./App.css";

const PAGE_SUBTITLES: Record<AppPageId, string> = {
  "case-builder": "Stage 1 · Case 构建",
  "agent-test": "Agent 测试执行",
  result: "批量执行结果",
};

export default function App() {
  const [navOpen, setNavOpen] = useState(false);
  const [activePage, setActivePage] = useState<AppPageId>("case-builder");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const activeNavItem = NAV_ITEMS.find((item) => item.id === activePage);

  return (
    <div className="app">
      <AppNav
        open={navOpen}
        activePage={activePage}
        onNavigate={setActivePage}
        onClose={() => setNavOpen(false)}
      />

      <header className="app-header">
        <div className="app-header-left">
          <button
            className="app-menu-btn"
            type="button"
            aria-label="打开导航"
            onClick={() => setNavOpen(true)}
          >
            ☰
          </button>
          <div>
            <h1>AutoTestVision</h1>
            <p>
              {activeNavItem
                ? `${activeNavItem.label} · ${PAGE_SUBTITLES[activePage]}`
                : PAGE_SUBTITLES[activePage]}
            </p>
          </div>
        </div>
        {statusMessage && <div className="status-banner">{statusMessage}</div>}
      </header>

      <div className="app-content">
        {activePage === "case-builder" && <CaseBuilderPage onStatusMessage={setStatusMessage} />}
        {activePage === "agent-test" && <AgentTestPage />}
        {activePage === "result" && <ResultPage />}
      </div>
    </div>
  );
}
