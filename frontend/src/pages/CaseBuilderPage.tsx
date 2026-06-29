import { useCallback, useEffect, useRef, useState } from "react";
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
import type { AgentTestBootstrap, CaseAgentExecMode } from "../types/navigation";
import type { CaseData, CaseStep, DeviceInfo, StepScreenBinding } from "../types";

interface CaseBuilderPageProps {
  onStatusMessage: (message: string | null) => void;
  onCaseSaved?: (bootstrap: AgentTestBootstrap) => void;
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

export default function CaseBuilderPage({ onStatusMessage, onCaseSaved }: CaseBuilderPageProps) {
  const [caseId, setCaseId] = useState<number | undefined>();
  const [caseName, setCaseName] = useState("未命名 Case");
  const [scriptContent, setScriptContent] = useState("");
  const [steps, setSteps] = useState<CaseStep[]>([createEmptyStep(0)]);
  const [saving, setSaving] = useState(false);
  const [stepExecuting, setStepExecuting] = useState(false);
  const [agentMode, setAgentMode] = useState<CaseAgentExecMode>("position");
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
      onStatusMessage("请先填写自然语言步骤描述");
      return;
    }
    if (!lastStep.description.trim()) {
      onStatusMessage("请先填写当前步骤描述，再添加步骤");
      return;
    }

    setStepExecuting(true);
    onStatusMessage(null);
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
      onStatusMessage(statusText);

      if (!stepOk && result.run.status === "failed") {
        return;
      }

      setSteps((prev) => [...prev, createEmptyStep(prev.length)]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "步骤执行失败";
      setLiveStatus(message);
      onStatusMessage(message);
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
    onStatusMessage(`步骤 ${index + 1} 已绑定屏幕截图`);
  };

  const handleAddPermissionPresetStep = (payload: { package: string; permissions: string[] }) => {
    setSteps((prev) =>
      [createPermissionPresetStep(0, payload), ...prev].map((step, index) => ({
        ...step,
        step_order: index,
      }))
    );
    onStatusMessage("已记录应用权限修改前置步骤（含包名与权限配置）");
  };

  const handleSave = async () => {
    setSaving(true);
    onStatusMessage(null);

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
        onStatusMessage(`已保存 Case #${savedCaseId}，可继续编写新 Case`);

        if (runId && onCaseSaved) {
          onCaseSaved({
            caseId: savedCaseId,
            runId,
            mode: agentMode,
            ...(runSnapshot ? { run: runSnapshot } : {}),
          });
        }
      }
    } catch (err) {
      onStatusMessage(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="workspace">
      <ScriptEditor value={scriptContent} onChange={setScriptContent} />
      <CaseBuilder
        caseName={caseName}
        steps={steps}
        saving={saving}
        stepExecuting={stepExecuting}
        agentMode={agentMode}
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
      />
    </main>
  );
}
