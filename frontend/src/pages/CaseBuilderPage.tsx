import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import CaseBuilder from "../components/CaseBuilder";
import DeviceScreen from "../components/DeviceScreen";
import ScriptEditor from "../components/ScriptEditor";
import {
  PERMISSION_PRESET_LABEL,
  PERMISSION_PRESET_STEP_TYPE,
} from "../constants/case";
import type { CaseData, CaseStep, DeviceInfo, StepScreenBinding } from "../types";

interface CaseBuilderPageProps {
  onStatusMessage: (message: string | null) => void;
}

function createEmptyStep(order: number): CaseStep {
  return { step_order: order, step_type: "natural", description: "" };
}

function createPermissionPresetStep(order: number): CaseStep {
  return {
    step_order: order,
    step_type: PERMISSION_PRESET_STEP_TYPE,
    description: PERMISSION_PRESET_LABEL,
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
  };
}

export default function CaseBuilderPage({ onStatusMessage }: CaseBuilderPageProps) {
  const [caseId, setCaseId] = useState<number | undefined>();
  const [caseName, setCaseName] = useState("未命名 Case");
  const [scriptContent, setScriptContent] = useState("");
  const [steps, setSteps] = useState<CaseStep[]>([createEmptyStep(0)]);
  const [saving, setSaving] = useState(false);

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
      // 静默失败，界面保持「未连接」，由用户点击刷新
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

  const handleAddStep = () => {
    setSteps((prev) => [...prev, createEmptyStep(prev.length)]);
  };

  const handleRemoveStep = (index: number) => {
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

  const resetCaseWorkspace = (savedCaseId: number) => {
    const initial = createInitialCaseState();
    setCaseId(initial.caseId);
    setCaseName(initial.caseName);
    setSteps(initial.steps);
    onStatusMessage(`已保存 Case #${savedCaseId}，操作区已清空，可开始编写新 Case`);
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

  const handleAddPermissionPresetStep = () => {
    setSteps((prev) =>
      [createPermissionPresetStep(0), ...prev].map((step, index) => ({
        ...step,
        step_order: index,
      }))
    );
    onStatusMessage("已记录应用权限修改前置步骤");
  };

  const handleSave = async () => {
    setSaving(true);
    onStatusMessage(null);

    const payload: CaseData = {
      name: caseName,
      script_content: scriptContent,
      steps: steps.map((step, index) => ({
        step_order: index,
        step_type: step.step_type ?? "natural",
        description: step.description,
        screen_image: step.screen_image ?? null,
        screen_width: step.screen_width ?? null,
        screen_height: step.screen_height ?? null,
        selection_x: step.selection_x ?? null,
        selection_y: step.selection_y ?? null,
        selection_width: step.selection_width ?? null,
        selection_height: step.selection_height ?? null,
      })),
    };

    try {
      const saved = caseId
        ? await api.updateCase(caseId, payload)
        : await api.createCase(payload);

      if (saved.id != null) {
        resetCaseWorkspace(saved.id);
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
        selectedSerial={selectedSerial}
        onCaseNameChange={setCaseName}
        onStepChange={handleStepChange}
        onStepScreenBind={handleStepScreenBind}
        onAddStep={handleAddStep}
        onRemoveStep={handleRemoveStep}
        onSave={handleSave}
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
