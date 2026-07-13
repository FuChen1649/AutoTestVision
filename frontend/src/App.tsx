import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import PlatformLayout from "./components/PlatformLayout";
import CaseBuilderPage from "./pages/CaseBuilderPage";
import CaseRecordPage from "./pages/CaseRecordPage";
import CaseListPage from "./pages/CaseListPage";
import TaskCenterPage from "./pages/TaskCenterPage";
import AgentGeneratePage from "./pages/AgentGeneratePage";
import AgentExecutePage from "./pages/AgentExecutePage";
import BatchPage from "./pages/BatchPage";
import ReportCenterPage from "./pages/ReportCenterPage";
import LogCenterPage from "./pages/LogCenterPage";
import DevicePage from "./pages/DevicePage";
import ResourcesPlaceholderPage from "./pages/ResourcesPlaceholderPage";
import AgentMonkeyTestPage from "./pages/AgentMonkeyTestPage";
import DataCleaningPage from "./pages/DataCleaningPage";
import DataFlywheelPage from "./pages/DataFlywheelPage";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<PlatformLayout />}>
          <Route index element={<Navigate to="/cases" replace />} />
          <Route path="cases" element={<CaseListPage />} />
          <Route path="cases/record" element={<CaseRecordPage />} />
          <Route path="cases/new" element={<CaseBuilderPage />} />
          <Route path="cases/:caseId/edit" element={<CaseBuilderPage />} />
          <Route path="tasks" element={<TaskCenterPage />} />
          <Route path="agent/generate" element={<AgentGeneratePage />} />
          <Route path="agent/generate/:caseId" element={<AgentGeneratePage />} />
          <Route path="agent/execute" element={<AgentExecutePage />} />
          <Route path="agent/execute/:caseId" element={<AgentExecutePage />} />
          <Route path="batch" element={<BatchPage />} />
          <Route path="reports" element={<ReportCenterPage />} />
          <Route path="logs" element={<LogCenterPage />} />
          <Route path="devices" element={<DevicePage />} />
          <Route path="resources" element={<ResourcesPlaceholderPage />} />
          <Route path="monkey" element={<AgentMonkeyTestPage />} />
          <Route path="data/cleaning" element={<DataCleaningPage />} />
          <Route path="data/flywheel" element={<DataFlywheelPage />} />
          {/* 旧路由兼容 */}
          <Route path="case-builder" element={<Navigate to="/cases/new" replace />} />
          <Route path="agent-test-position" element={<Navigate to="/agent/execute?mode=position" replace />} />
          <Route path="agent-test-code" element={<Navigate to="/agent/execute?mode=code" replace />} />
          <Route path="result" element={<Navigate to="/reports" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
