import { useState } from "react";
import { PERMISSION_PRESET_LABEL, PERMISSION_PRESET_STEP_TYPE } from "../constants/case";
import type { CaseStep, StepScreenBinding } from "../types";
import StepScreenCaptureModal from "./StepScreenCaptureModal";

function isPermissionPresetStep(step: CaseStep) {
  return step.step_type === PERMISSION_PRESET_STEP_TYPE;
}

interface CaseBuilderProps {
  caseName: string;
  steps: CaseStep[];
  saving: boolean;
  selectedSerial: string | null;
  onCaseNameChange: (name: string) => void;
  onStepChange: (index: number, description: string) => void;
  onStepScreenBind: (index: number, binding: StepScreenBinding) => void;
  onAddStep: () => void;
  onRemoveStep: (index: number) => void;
  onSave: () => void;
}

export default function CaseBuilder({
  caseName,
  steps,
  saving,
  selectedSerial,
  onCaseNameChange,
  onStepChange,
  onStepScreenBind,
  onAddStep,
  onRemoveStep,
  onSave,
}: CaseBuilderProps) {
  const [captureStepIndex, setCaptureStepIndex] = useState<number | null>(null);

  return (
    <section className="panel case-panel">
      <header className="panel-header case-header">
        <div>
          <h2>自然语言 Case</h2>
          <span className="panel-hint">单步描述：action + position + color? + text/shape/icon</span>
        </div>
        <button className="primary-btn" onClick={onSave} disabled={saving}>
          {saving ? "保存中..." : "保存 Case"}
        </button>
      </header>

      <div className="panel-body case-body">
        <label className="field-label">
          Case 名称
          <input
            className="text-input"
            value={caseName}
            onChange={(event) => onCaseNameChange(event.target.value)}
            placeholder="输入 Case 名称"
          />
        </label>

        <div className="steps-list">
          {steps.map((step, index) => {
            const isPreset = isPermissionPresetStep(step);
            const hasScreen = Boolean(step.screen_image);

            return (
              <div
                className={isPreset ? "step-item step-item-preset" : "step-item"}
                key={`step-${index}-${step.step_type ?? "natural"}`}
              >
                <div className={isPreset ? "step-index step-index-preset" : "step-index"}>
                  {index + 1}
                </div>
                {isPreset ? (
                  <div className="step-preset" title="前置步骤，不展示权限明细，可删除">
                    <strong>{PERMISSION_PRESET_LABEL}</strong>
                  </div>
                ) : (
                  <div className="step-input-wrap">
                    <textarea
                      className="step-input"
                      value={step.description}
                      onChange={(event) => onStepChange(index, event.target.value)}
                      placeholder="例如：点击屏幕右上角蓝色的设置图标"
                      rows={3}
                    />
                    <button
                      className={hasScreen ? "step-capture-btn step-capture-btn-bound" : "step-capture-btn"}
                      type="button"
                      title={hasScreen ? "已绑定屏幕截图，点击重新框选" : "框选当前设备屏幕"}
                      onClick={() => setCaptureStepIndex(index)}
                    >
                      {hasScreen ? "图" : "屏"}
                    </button>
                    {hasScreen && step.screen_image && (
                      <img
                        className="step-screen-thumb"
                        src={step.screen_image}
                        alt={`步骤 ${index + 1} 截图`}
                      />
                    )}
                  </div>
                )}
                {(isPreset ||
                  steps.filter((item) => !isPermissionPresetStep(item)).length > 1) && (
                  <button
                    className="icon-btn remove-btn"
                    onClick={() => onRemoveStep(index)}
                    title={isPreset ? "删除权限前置步骤" : "删除步骤"}
                    type="button"
                  >
                    ×
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <button className="add-step-btn" onClick={onAddStep} type="button">
          <span className="add-icon">+</span>
          添加步骤
        </button>
      </div>

      <StepScreenCaptureModal
        open={captureStepIndex !== null}
        serial={selectedSerial}
        stepIndex={captureStepIndex ?? 0}
        onClose={() => setCaptureStepIndex(null)}
        onSave={onStepScreenBind}
      />
    </section>
  );
}
