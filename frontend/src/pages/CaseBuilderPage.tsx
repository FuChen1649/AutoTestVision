import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { caseLiveApi } from "../api/caseLive";
import { api } from "../api/client";
import CaseBuilder from "../components/CaseBuilder";
import DeviceScreen from "../components/DeviceScreen";
import ScriptEditor from "../components/ScriptEditor";
import {
  PERMISSION_PRESET_LABEL,
  PERMISSION_PRESET_STEP_TYPE,
} from "../constants/case";
import type { AgentRunState } from "../types/agent";
import type { CaseAgentExecMode } from "../types/navigation";
import type { CaseData, CaseStep, DeviceInfo, StepScreenBinding } from "../types";

interface CaseBuilderPageProps {
  onStatusMessage?: (message: string | null) => void;
  onCaseSaved?: (payload: { caseId: number; runId: string; mode: CaseAgentExecMode; run?: AgentRunState }) => void;
}

function createEmptyStep(order: number): CaseStep {
  return { step_order: order, step_type: "natural", description: "" };
}

function createPermissionPresetStep(
  order: number,
  metadata?: { package: string; permissions: string[] }
): CaseStep {
  return {
    step_order: order,
    step_type: PERMISSION_PRESET_STEP_TYPE,
    description: PERMISSION_PRESET_LABEL,
    metadata_json: metadata
      ? { tool: "apply_app_permissions", ...metadata }
      : undefined,
  };
}

function isPermissionPresetStep(step: CaseStep) {
  return step.step_type === PERMISSION_PRESET_STEP_TYPE;
}

function createInitialCaseState() {
  return {
    caseId: undefined as number | undefined,
    caseName: "未命名 Case",
    steps: [createEmptyStep(0)] as CaseStep[],
    liveRunId: undefined as string | undefined,
  };
}

function buildCasePayload(
  caseName: string,
  scriptContent: string,
  steps: CaseStep[]
): CaseData {
  return {
    name: caseName,
    script_content: scriptContent,
    steps: steps.map((step, index) => ({
      step_order: index,
      step_type: step.step_type ?? "natural",
      description: step.description,
      metadata_json: step.metadata_json ?? null,
      screen_image: step.screen_image ?? null,
      screen_width: step.screen_width ?? null,
      screen_height: step.screen_height ?? null,
      selection_x: step.selection_x ?? null,
      selection_y: step.selection_y ?? null,
      selection_width: step.selection_width ?? null,
      selection_height: step.selection_height ?? null,
    })),
  };
}

const LIVE_EXEC_STORAGE_KEY = "case-builder-live-exec";

function readLiveExecPreference(): boolean {
  try {
    return localStorage.getItem(LIVE_EXEC_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export default function CaseBuilderPage({ onStatusMessage, onCaseSaved }: CaseBuilderPageProps) {
  const navigate = useNavigate();
  const { caseId: caseIdParam } = useParams();
  const editCaseId = caseIdParam ? Number(caseIdParam) : undefined;

  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const notify = onStatusMessage ?? setStatusMessage;

  const [caseId, setCaseId] = useState<number | undefined>(editCaseId);
  const [caseName, setCaseName] = useState("未命名 Case");
  const [scriptContent, setScriptContent] = useState("");
  const [steps, setSteps] = useState<CaseStep[]>([createEmptyStep(0)]);
  const [saving, setSaving] = useState(false);
  const [stepExecuting, setStepExecuting] = useState(false);
  const [agentMode, setAgentMode] = useState<CaseAgentExecMode>("position");
  const [liveExecEnabled, setLiveExecEnabled] = useState(readLiveExecPreference);
  const [liveRunId, setLiveRunId] = useState<string | undefined>();
  const [liveRunState, setLiveRunState] = useState<AgentRunState | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(true);
  const selectedSerialRef = useRef<string | null>(null);

  useEffect(() => {
    selectedSerialRef.current = selectedSerial;
  }, [selectedSerial]);

  useEffect(() => {
    if (!editCaseId) return;
    void (async () => {
      try {
        const data = await api.getCase(editCaseId);
        setCaseId(data.id);
        setCaseName(data.name);
        setScriptContent(data.script_content ?? "");
        setSteps(
          data.steps.length > 0
            ? data.steps.map((s) => ({
                step_order: s.step_order,
                step_type: s.step_type,
                description: s.description,
                metadata_json: s.metadata_json ?? undefined,
                screen_image: s.screen_image ?? undefined,
                screen_width: s.screen_width ?? undefined,
                screen_height: s.screen_height ?? undefined,
                selection_x: s.selection_x ?? undefined,
                selection_y: s.selection_y ?? undefined,
                selection_width: s.selection_width ?? undefined,
                selection_height: s.selection_height ?? undefined,
              }))
            : [createEmptyStep(0)]
        );
      } catch (err) {
        notify(err instanceof Error ? err.message : "加载 Case 失败");
      }
    })();
  }, [editCaseId, notify]);

  const refreshDevices = useCallback(async () => {
    try {
      const list = await api.listDevices();
      setDevices(list);

      if (list.length > 0) {
        const current = selectedSerialRef.current;
        const nextSerial =
          current && list.some((device) => device.serial === current)
            ? current
            : list[0].serial;

        if (nextSerial !== current) {
          setSelectedSerial(nextSerial);
          selectedSerialRef.current = nextSerial;
        }

        await api.selectDevice(nextSerial);
      } else if (!selectedSerialRef.current) {
        setSelectedSerial(null);
      }
    } catch {
      // 静默失败
    } finally {
      setDeviceLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshDevices();

    let fastAttempts = 0;
    const fastTimer = window.setInterval(() => {
      fastAttempts += 1;
      void refreshDevices();
      if (fastAttempts >= 12) {
        window.clearInterval(fastTimer);
      }
    }, 1000);

    const slowTimer = window.setInterval(() => void refreshDevices(), 5000);
    return () => {
      window.clearInterval(fastTimer);
      window.clearInterval(slowTimer);
    };
  }, [refreshDevices]);

  const handleSelectDevice = async (serial: string) => {
    setSelectedSerial(serial);
    await api.selectDevice(serial);
  };

  const handleAddStep = async () => {
    if (stepExecuting || saving) {
      return;
    }

    const lastIndex = steps.length - 1;
    const lastStep = steps[lastIndex];
    if (!lastStep || isPermissionPresetStep(lastStep)) {
      notify("请先填写自然语言步骤描述");
      return;
    }
    if (!lastStep.description.trim()) {
      notify("请先填写当前步骤描述，再添加步骤");
      return;
    }

    if (!liveExecEnabled) {
      setSteps((prev) => [...prev, createEmptyStep(prev.length)]);
      notify(`已添加步骤 ${lastIndex + 1}，继续编写下一步`);
      return;
    }

    if (!selectedSerial) {
      notify("请先连接设备后再开启实时执行");
      return;
    }

    setStepExecuting(true);
    notify(null);
    setLiveStatus(`正在执行步骤 ${lastIndex + 1}（${agentMode === "position" ? "Position" : "Code"}）…`);

    const payload = buildCasePayload(caseName, scriptContent, steps);

    try {
      const result = await caseLiveApi.executeStep({
        case_id: caseId,
        case_name: payload.name,
        script_content: payload.script_content,
        steps: payload.steps,
        commit_step_index: lastIndex,
        agent_mode: agentMode,
        run_id: liveRunId,
        serial: selectedSerial,
      });

      if (result.case.id != null) {
        setCaseId(result.case.id);
      }
      setLiveRunId(result.run_id);
      if (agentMode === "position") {
        setLiveRunState(result.run as AgentRunState);
      }

      const stepRecord = result.run.steps?.[lastIndex];
      const stepOk = stepRecord?.status === "success";
      const statusText = stepOk
        ? `步骤 ${lastIndex + 1} 执行成功`
        : `步骤 ${lastIndex + 1}：${result.message}`;

      setLiveStatus(statusText);
      notify(statusText);

      if (!stepOk && result.run.status === "failed") {
        return;
      }

      setSteps((prev) => [...prev, createEmptyStep(prev.length)]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "步骤执行失败";
      setLiveStatus(message);
      notify(message);
    } finally {
      setStepExecuting(false);
    }
  };

  const handleRemoveStep = (index: number) => {
    if (stepExecuting) {
      return;
    }
    setSteps((prev) => {
      const target = prev[index];
      if (!target) {
        return prev;
      }

      if (!isPermissionPresetStep(target)) {
        const naturalCount = prev.filter((step) => !isPermissionPresetStep(step)).length;
        if (naturalCount <= 1) {
          return prev;
        }
      }

      const next = prev
        .filter((_, stepIndex) => stepIndex !== index)
        .map((step, stepIndex) => ({ ...step, step_order: stepIndex }));

      return next.length > 0 ? next : [createEmptyStep(0)];
    });
  };

  const resetCaseWorkspace = () => {
    const initial = createInitialCaseState();
    setCaseId(initial.caseId);
    setCaseName(initial.caseName);
    setSteps(initial.steps);
    setScriptContent("");
    setLiveRunId(initial.liveRunId);
    setLiveRunState(null);
    setLiveStatus(null);
  };

  const handleStepChange = (index: number, description: string) => {
    setSteps((prev) =>
      prev.map((step, stepIndex) => {
        if (stepIndex !== index || isPermissionPresetStep(step)) {
          return step;
        }
        return { ...step, description };
      })
    );
  };

  const handleStepScreenBind = (index: number, binding: StepScreenBinding) => {
    setSteps((prev) =>
      prev.map((step, stepIndex) => (stepIndex === index ? { ...step, ...binding } : step))
    );
    notify(`步骤 ${index + 1} 已绑定屏幕截图`);
  };

  const handleAddPermissionPresetStep = (payload: { package: string; permissions: string[] }) => {
    setSteps((prev) =>
      [createPermissionPresetStep(0, payload), ...prev].map((step, index) => ({
        ...step,
        step_order: index,
      }))
    );
    notify("已记录应用权限修改前置步骤（含包名与权限配置）");
  };

  const handleLiveExecToggle = (enabled: boolean) => {
    setLiveExecEnabled(enabled);
    try {
      localStorage.setItem(LIVE_EXEC_STORAGE_KEY, enabled ? "1" : "0");
    } catch {
      // ignore
    }
    if (!enabled) {
      setLiveRunId(undefined);
      setLiveRunState(null);
      setLiveStatus(null);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    notify(null);

    const payload = buildCasePayload(caseName, scriptContent, steps);

    try {
      const saved = caseId
        ? await api.updateCase(caseId, payload)
        : await api.createCase(payload);

      if (saved.id != null) {
        const savedCaseId = saved.id;
        const runId = liveRunId;
        const runSnapshot = agentMode === "position" ? liveRunState : null;
        resetCaseWorkspace();
        notify(`已保存 Case #${savedCaseId}`);
        if (runId && onCaseSaved) {
          onCaseSaved({
            caseId: savedCaseId,
            runId,
            mode: agentMode,
            ...(runSnapshot ? { run: runSnapshot } : {}),
          });
        } else {
          navigate(`/cases/${savedCaseId}/edit`);
        }
      }
    } catch (err) {
      notify(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {statusMessage && <div className="status-banner">{statusMessage}</div>}
      <main className="workspace">
      <ScriptEditor value={scriptContent} onChange={setScriptContent} />
      <CaseBuilder
        caseName={caseName}
        steps={steps}
        saving={saving}
        stepExecuting={stepExecuting}
        agentMode={agentMode}
        liveExecEnabled={liveExecEnabled}
        liveStatus={liveStatus}
        selectedSerial={selectedSerial}
        onCaseNameChange={setCaseName}
        onAgentModeChange={(mode) => {
          if (mode !== agentMode) {
            setLiveRunId(undefined);
            setLiveStatus(null);
          }
          setAgentMode(mode);
        }}
        onLiveExecToggle={handleLiveExecToggle}
        onStepChange={handleStepChange}
        onStepScreenBind={handleStepScreenBind}
        onAddStep={() => void handleAddStep()}
        onRemoveStep={handleRemoveStep}
        onSave={() => void handleSave()}
      />
      <DeviceScreen
        devices={devices}
        selectedSerial={selectedSerial}
        deviceLoading={deviceLoading}
        onRefreshDevices={refreshDevices}
        onSelectDevice={handleSelectDevice}
        onPermissionPresetAdded={handleAddPermissionPresetStep}
        showNavKeys
      />
    </main>
    </>
  );
}
