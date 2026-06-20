import { useState } from "react";
import AppNav from "./components/AppNav";
import AgentMonkeyTestPage from "./pages/AgentMonkeyTestPage";
import AgentTestCodePage from "./pages/AgentTestCodePage";
import AgentTestPage from "./pages/AgentTestPage";
import CaseBuilderPage from "./pages/CaseBuilderPage";
import DataCleaningPage from "./pages/DataCleaningPage";
import DataFlywheelPage from "./pages/DataFlywheelPage";
import ResultPage from "./pages/ResultPage";
import { NAV_ITEMS, type AppPageId } from "./types/navigation";
import "./App.css";

const PAGE_SUBTITLES: Record<AppPageId, string> = {
  "case-builder": "Stage 1 · Case 构建",
  "agent-test-position": "坐标意图 · 触控执行",
  "agent-test-code": "代码意图 · pytest 执行",
  "agent-monkey-test": "应用探索 · 树形导航",
  result: "批量执行结果",
  "data-cleaning": "数据清洗",
  "data-flywheel": "数据飞轮",
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
        {activePage === "agent-test-position" && <AgentTestPage />}
        {activePage === "agent-test-code" && <AgentTestCodePage />}
        {activePage === "agent-monkey-test" && <AgentMonkeyTestPage />}
        {activePage === "result" && <ResultPage />}
        {activePage === "data-cleaning" && <DataCleaningPage />}
        {activePage === "data-flywheel" && <DataFlywheelPage />}
      </div>
    </div>
  );
}
