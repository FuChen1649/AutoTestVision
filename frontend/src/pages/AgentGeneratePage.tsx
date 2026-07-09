import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { scriptGenApi, type CaseScriptsResponse, type ScriptGenPrerequisites } from "../api/platform";
import { agentApi } from "../api/agent";
import { isApiOfflineError } from "../api/http";
import type { ProviderInfo } from "../types/agent";
import DeviceLiveMirror from "../components/DeviceLiveMirror";
import "./PlatformPages.css";
import "./AgentGeneratePage.css";

type StepStatus = "pending" | "generating" | "ready" | "failed";

interface PathStepLive {
  stepOrder: number;
  description: string;
  status: StepStatus;
  isAssertion?: boolean;
  serial?: string;
  beforeImage?: string;
  beforeAnnotated?: string;
  afterImage?: string;
  scriptText?: string;
}

function formatPositionScript(script: Record<string, unknown> | null | undefined): string {
  if (!script) return "—";
  const action = String(script.action ?? "tap");
  if (action === "skip") return "skip · 无需 UI 操作";
  if (action === "swipe") {
    return `swipe (${script.x},${script.y}) → (${script.x2},${script.y2}) · ${script.reasoning ?? ""}`.trim();
  }
  return `${action} (${script.x}, ${script.y}) · conf=${script.confidence ?? "?"} · ${script.reasoning ?? ""}`.trim();
}

function formatCodeScript(script: Record<string, unknown> | null | undefined): string {
  if (!script) return "—";
  const line = String(script.code_line ?? "").trim();
  if (!line) return script.reasoning ? String(script.reasoning) : "—";
  return `${line}\n# ${script.reasoning ?? ""}`.trim();
}

function positionStepFromApi(step: CaseScriptsResponse["steps"][0]): PathStepLive {
  return {
    stepOrder: step.step_order,
    description: step.description,
    isAssertion: Boolean(step.is_assertion),
    status: step.position_script ? "ready" : ((step.script_status as StepStatus) ?? "pending"),
    scriptText: step.position_script
      ? formatPositionScript(step.position_script as Record<string, unknown>)
      : undefined,
  };
}

function codeStepFromApi(step: CaseScriptsResponse["steps"][0]): PathStepLive {
  return {
    stepOrder: step.step_order,
    description: step.description,
    isAssertion: Boolean(step.is_assertion),
    status: step.code_script ? "ready" : ((step.script_status as StepStatus) ?? "pending"),
    scriptText: step.code_script
      ? formatCodeScript(step.code_script as Record<string, unknown>)
      : undefined,
  };
}

function emptyPathSteps(
  descriptions: { step_order: number; description: string; is_assertion?: boolean }[]
): PathStepLive[] {
  return descriptions.map((s) => ({
    stepOrder: s.step_order,
    description: s.description,
    isAssertion: Boolean(s.is_assertion),
    status: "pending",
  }));
}

export default function AgentGeneratePage() {
  const { caseId: caseIdParam } = useParams();
  const navigate = useNavigate();
  const stopStreamRef = useRef<(() => void) | null>(null);
  const positionStepRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const codeStepRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  const [cases, setCases] = useState<{ id: number; name: string }[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(
    caseIdParam ? Number(caseIdParam) : null
  );
  const [scripts, setScripts] = useState<CaseScriptsResponse | null>(null);
  const [prerequisites, setPrerequisites] = useState<ScriptGenPrerequisites | null>(null);
  const [positionSerial, setPositionSerial] = useState("");
  const [codeSerial, setCodeSerial] = useState("");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [generating, setGenerating] = useState(false);

  const [positionSteps, setPositionSteps] = useState<PathStepLive[]>([]);
  const [codeSteps, setCodeSteps] = useState<PathStepLive[]>([]);
  const [positionSelectedOrder, setPositionSelectedOrder] = useState<number | null>(null);
  const [codeSelectedOrder, setCodeSelectedOrder] = useState<number | null>(null);
  const [positionActiveOrder, setPositionActiveOrder] = useState<number | null>(null);
  const [codeActiveOrder, setCodeActiveOrder] = useState<number | null>(null);
  const [positionLog, setPositionLog] = useState("");
  const [codeLog, setCodeLog] = useState("");
  const [completionLog, setCompletionLog] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [positionLiveExpanded, setPositionLiveExpanded] = useState(true);
  const [codeLiveExpanded, setCodeLiveExpanded] = useState(true);

  const scrollPathStep = useCallback(
    (path: "position" | "code", stepOrder: number) => {
      const el = (path === "position" ? positionStepRefs : codeStepRefs).current.get(stepOrder);
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    []
  );

  const advancePathStep = useCallback(
    (path: "position" | "code", completedOrder: number) => {
      const readSteps = path === "position" ? setPositionSteps : setCodeSteps;
      readSteps((prev) => {
        const idx = prev.findIndex((s) => s.stepOrder === completedOrder);
        const next = idx >= 0 ? prev[idx + 1] : undefined;
        if (next) {
          window.setTimeout(() => {
            if (path === "position") {
              setPositionSelectedOrder(next.stepOrder);
              scrollPathStep("position", next.stepOrder);
            } else {
              setCodeSelectedOrder(next.stepOrder);
              scrollPathStep("code", next.stepOrder);
            }
          }, 200);
        }
        return prev;
      });
    },
    [scrollPathStep]
  );

  const loadPrerequisites = useCallback(
    async (pos?: string, code?: string) => {
      try {
        const data = await scriptGenApi.checkPrerequisites({
          position_serial: pos || undefined,
          code_serial: code || undefined,
        });
        setPrerequisites(data);
        if (data.position_serial) setPositionSerial(data.position_serial);
        if (data.code_serial) setCodeSerial(data.code_serial);
      } catch {
        if (!generating) setPrerequisites(null);
      }
    },
    [generating]
  );

  const handlePositionDeviceChange = useCallback(
    (serial: string) => {
      setPositionSerial(serial);
      const other = prerequisites?.devices.find((d) => d.serial !== serial)?.serial;
      if (other) setCodeSerial(other);
      void loadPrerequisites(serial, other);
    },
    [loadPrerequisites, prerequisites?.devices]
  );

  const handleCodeDeviceChange = useCallback(
    (serial: string) => {
      setCodeSerial(serial);
      const other = prerequisites?.devices.find((d) => d.serial !== serial)?.serial;
      if (other) setPositionSerial(other);
      void loadPrerequisites(other, serial);
    },
    [loadPrerequisites, prerequisites?.devices]
  );

  const loadCases = useCallback(async () => {
    try {
      const list = await agentApi.listCases(100);
      setCases(list.map((c) => ({ id: c.id, name: c.name })));
      if (!selectedCaseId && list[0]) setSelectedCaseId(list[0].id);
    } catch (err) {
      if (!isApiOfflineError(err)) setError(err instanceof Error ? err.message : "加载 Case 失败");
    }
  }, [selectedCaseId]);

  const loadScripts = useCallback(async (caseId: number) => {
    try {
      const data = await scriptGenApi.getScripts(caseId);
      setScripts(data);
      setPositionSteps(data.steps.map(positionStepFromApi));
      setCodeSteps(data.steps.map(codeStepFromApi));
      setPositionSelectedOrder((c) => c ?? data.steps[0]?.step_order ?? null);
      setCodeSelectedOrder((c) => c ?? data.steps[0]?.step_order ?? null);
    } catch (err) {
      if (!isApiOfflineError(err)) setError(err instanceof Error ? err.message : "加载脚本失败");
    }
  }, []);

  useEffect(() => {
    void loadCases();
    void loadPrerequisites();
    void agentApi.listProviders().then((resp) => {
      const reachable = resp.providers.filter((p) => p.available);
      setProviders(reachable);
      setSelectedProvider(reachable[0]?.id ?? "");
    });
    const timer = window.setInterval(() => void loadPrerequisites(), 5000);
    return () => window.clearInterval(timer);
  }, [loadCases, loadPrerequisites]);

  useEffect(() => {
    if (selectedCaseId) {
      void loadScripts(selectedCaseId);
      navigate(`/agent/generate/${selectedCaseId}`, { replace: true });
    }
  }, [selectedCaseId, loadScripts, navigate]);

  const updatePositionStep = useCallback(
    (stepOrder: number, updater: (step: PathStepLive) => PathStepLive) => {
      setPositionSteps((prev) => prev.map((s) => (s.stepOrder === stepOrder ? updater(s) : s)));
    },
    []
  );

  const updateCodeStep = useCallback(
    (stepOrder: number, updater: (step: PathStepLive) => PathStepLive) => {
      setCodeSteps((prev) => prev.map((s) => (s.stepOrder === stepOrder ? updater(s) : s)));
    },
    []
  );

  const applyPositionEvent = useCallback(
    (name: string, stepOrder: number, detail: Record<string, unknown>, message: string) => {
      setPositionLog(message || name);
      setPositionActiveOrder(stepOrder);
      if (name !== "position_executed") {
        setPositionSelectedOrder(stepOrder);
        scrollPathStep("position", stepOrder);
      }

      if (name === "position_step_start") {
        updatePositionStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          serial: String(detail.serial ?? positionSerial ?? s.serial ?? ""),
        }));
      }

      if (name === "position_capture") {
        updatePositionStep(stepOrder, (s) => ({
          ...s,
          serial: String(detail.serial ?? s.serial ?? ""),
          beforeImage: String(detail.before_image ?? s.beforeImage ?? ""),
        }));
      }

      if (name === "position_script_ready") {
        updatePositionStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          beforeImage: String(detail.before_image ?? s.beforeImage ?? ""),
          beforeAnnotated: String(detail.before_image_annotated ?? s.beforeAnnotated ?? ""),
          scriptText: formatPositionScript(detail.script as Record<string, unknown>),
        }));
      }

      if (name === "position_executed") {
        const execError = detail.exec_error ? String(detail.exec_error) : null;
        updatePositionStep(stepOrder, (s) => ({
          ...s,
          status: execError ? "failed" : "ready",
          serial: String(detail.serial ?? s.serial ?? ""),
          afterImage: String(detail.after_image ?? s.afterImage ?? ""),
          scriptText: execError
            ? `${s.scriptText ?? "—"}\n\n⚠ 执行失败:\n${execError.slice(0, 400)}`
            : s.scriptText,
        }));
        advancePathStep("position", stepOrder);
      }

      if (name === "position_error") {
        updatePositionStep(stepOrder, (s) => ({ ...s, status: "failed" }));
        setError(message || "Position 生成失败");
      }
    },
    [advancePathStep, positionSerial, scrollPathStep, updatePositionStep]
  );

  const applyCodeEvent = useCallback(
    (name: string, stepOrder: number, detail: Record<string, unknown>, message: string) => {
      setCodeLog(message || name);
      setCodeActiveOrder(stepOrder);
      if (name !== "code_executed") {
        setCodeSelectedOrder(stepOrder);
        scrollPathStep("code", stepOrder);
      }

      if (name === "code_step_start") {
        updateCodeStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          serial: String(detail.serial ?? codeSerial ?? s.serial ?? ""),
        }));
      }

      if (name === "code_capture") {
        updateCodeStep(stepOrder, (s) => ({
          ...s,
          serial: String(detail.serial ?? s.serial ?? ""),
          beforeImage: String(detail.before_image ?? s.beforeImage ?? ""),
        }));
      }

      if (name === "code_script_ready") {
        updateCodeStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          beforeImage: String(detail.before_image ?? s.beforeImage ?? ""),
          scriptText: formatCodeScript(detail.script as Record<string, unknown>),
        }));
      }

      if (name === "code_executed") {
        const execError = detail.exec_error ? String(detail.exec_error) : null;
        const script = detail.script as Record<string, unknown> | undefined;
        updateCodeStep(stepOrder, (s) => ({
          ...s,
          status: execError ? "failed" : "ready",
          serial: String(detail.serial ?? s.serial ?? ""),
          afterImage: String(detail.after_image ?? s.afterImage ?? ""),
          scriptText: execError
            ? `${s.scriptText ?? formatCodeScript(script)}\n\n⚠ 执行失败:\n${execError.slice(0, 400)}`
            : s.scriptText ?? (script ? formatCodeScript(script) : undefined),
        }));
        advancePathStep("code", stepOrder);
      }

      if (name === "code_error") {
        updateCodeStep(stepOrder, (s) => ({ ...s, status: "failed" }));
        setError(message || "Code 生成失败");
      }
    },
    [advancePathStep, codeSerial, scrollPathStep, updateCodeStep]
  );

  const applyAssertionEvent = useCallback(
    (name: string, stepOrder: number, detail: Record<string, unknown>, message: string) => {
      const logText = message || name;
      setPositionLog(logText);
      setCodeLog(logText);
      setPositionActiveOrder(stepOrder);
      setCodeActiveOrder(stepOrder);
      setPositionSelectedOrder(stepOrder);
      setCodeSelectedOrder(stepOrder);
      scrollPathStep("position", stepOrder);
      scrollPathStep("code", stepOrder);

      const patch = (s: PathStepLive): PathStepLive => {
        const next: PathStepLive = { ...s, isAssertion: true, status: "generating" };
        if (name === "assertion_start") {
          return next;
        }
        const success = name === "assertion_passed";
        const posImg = detail.position_image ? String(detail.position_image) : s.beforeImage;
        const verify = detail.verify as Record<string, unknown> | undefined;
        const reasoning = verify?.reasoning ? String(verify.reasoning) : logText;
        return {
          ...next,
          status: success ? "ready" : "failed",
          beforeImage: posImg,
          afterImage: posImg,
          scriptText: `断言验证 · ${success ? "通过" : "未通过"}\n${reasoning}`,
        };
      };

      updatePositionStep(stepOrder, patch);
      updateCodeStep(stepOrder, (s) => ({
        ...patch(s),
        beforeImage: detail.code_image ? String(detail.code_image) : s.beforeImage,
        afterImage: detail.code_image ? String(detail.code_image) : s.afterImage,
      }));

      if (name === "assertion_failed") {
        setError(message || "断言未通过，Case 已终止");
        setGenerating(false);
      }
      if (name === "assertion_passed") {
        advancePathStep("position", stepOrder);
        advancePathStep("code", stepOrder);
      }
    },
    [advancePathStep, scrollPathStep, updateCodeStep, updatePositionStep]
  );

  const applyStreamEvent = useCallback(
    (event: Record<string, unknown>) => {
      const name = String(event.event ?? "");
      const stepOrder = event.step_order != null ? Number(event.step_order) : null;
      const detail = (event.detail ?? {}) as Record<string, unknown>;
      const message = String(event.message ?? "");

      if (name === "completion_verify_start" || name === "completion_verify_done") {
        setCompletionLog(message || name);
        return;
      }
      if (name === "completion_verify_step" || name === "assertion_dual_review") {
        setCompletionLog(message || name);
        return;
      }

      if (stepOrder == null) {
        if (name === "started") {
          const pos = detail.position_serial ? String(detail.position_serial) : "";
          const code = detail.code_serial ? String(detail.code_serial) : "";
          if (pos) setPositionSerial(pos);
          if (code) setCodeSerial(code);
        }
        if (name === "completed" || name === "error" || name === "cancelled") {
          setGenerating(false);
          setPositionActiveOrder(null);
          setCodeActiveOrder(null);
        }
        return;
      }

      if (
        name === "assertion_start" ||
        name === "assertion_passed" ||
        name === "assertion_failed"
      ) {
        applyAssertionEvent(name, stepOrder, detail, message);
        return;
      }

      if (name.startsWith("position_")) {
        applyPositionEvent(name, stepOrder, detail, message);
        return;
      }
      if (name.startsWith("code_")) {
        applyCodeEvent(name, stepOrder, detail, message);
      }
    },
    [applyAssertionEvent, applyCodeEvent, applyPositionEvent]
  );

  const canGenerate = Boolean(
    selectedCaseId &&
      prerequisites?.ready &&
      positionSerial &&
      codeSerial &&
      positionSerial !== codeSerial
  );

  const handleGenerate = async () => {
    if (!selectedCaseId || generating || !canGenerate || !scripts) return;
    setGenerating(true);
    setError(null);
    setPositionLog("Position 路径启动…");
    setCodeLog("Code 路径启动…");
    stopStreamRef.current?.();

    const descriptions = scripts.steps.map((s) => ({
      step_order: s.step_order,
      description: s.description,
      is_assertion: s.is_assertion,
    }));
    setPositionSteps(emptyPathSteps(descriptions));
    setCodeSteps(emptyPathSteps(descriptions));

    const firstOrder = scripts.steps[0]?.step_order;
    if (firstOrder != null) {
      setPositionSelectedOrder(firstOrder);
      setCodeSelectedOrder(firstOrder);
      window.setTimeout(() => {
        scrollPathStep("position", firstOrder);
        scrollPathStep("code", firstOrder);
      }, 100);
    }

    try {
      const resp = await scriptGenApi.start(selectedCaseId, {
        position_serial: positionSerial || undefined,
        code_serial: codeSerial || undefined,
        llm_provider: selectedProvider || undefined,
      });
      stopStreamRef.current = scriptGenApi.stream(resp.task_uuid, (event) => {
        applyStreamEvent(event);
        if (event.event === "completed") {
          void loadScripts(selectedCaseId);
        }
      });
    } catch (err) {
      setGenerating(false);
      setError(err instanceof Error ? err.message : "启动生成失败");
    }
  };

  useEffect(() => () => stopStreamRef.current?.(), []);

  const positionViewOrder =
    positionSelectedOrder ?? positionActiveOrder ?? positionSteps[0]?.stepOrder ?? null;
  const codeViewOrder = codeSelectedOrder ?? codeActiveOrder ?? codeSteps[0]?.stepOrder ?? null;

  const positionViewStep = useMemo(
    () => positionSteps.find((s) => s.stepOrder === positionViewOrder) ?? null,
    [positionSteps, positionViewOrder]
  );
  const codeViewStep = useMemo(
    () => codeSteps.find((s) => s.stepOrder === codeViewOrder) ?? null,
    [codeSteps, codeViewOrder]
  );

  const positionDone = positionSteps.filter((s) => s.status === "ready").length;
  const codeDone = codeSteps.filter((s) => s.status === "ready").length;
  const totalSteps = positionSteps.length;

  const progressText = generating
    ? `Pos ${positionDone}/${totalSteps} · Code ${codeDone}/${totalSteps}${completionLog ? ` · ${completionLog}` : ""}`
    : scripts?.script_status
      ? `脚本状态 · ${scripts.script_status}${completionLog ? ` · ${completionLog}` : ""}`
      : completionLog || "";

  return (
    <div className="platform-page dual-gen-page">
      <div className="dual-gen-toolbar">
        <select
          className="platform-select"
          value={selectedCaseId ?? ""}
          onChange={(e) => setSelectedCaseId(Number(e.target.value))}
        >
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          className="platform-select"
          value={selectedProvider}
          onChange={(e) => setSelectedProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <select
          className="platform-select dual-gen-device-select"
          value={positionSerial}
          disabled={generating || !prerequisites?.devices.length}
          onChange={(e) => handlePositionDeviceChange(e.target.value)}
          title="Position 坐标脚本在此设备执行"
        >
          {(prerequisites?.devices ?? []).map((d) => (
            <option key={`pos-${d.serial}`} value={d.serial} disabled={d.serial === codeSerial}>
              Pos · {d.model || d.serial.slice(-8)} ({d.serial.slice(-6)})
            </option>
          ))}
        </select>
        <select
          className="platform-select dual-gen-device-select"
          value={codeSerial}
          disabled={generating || !prerequisites?.devices.length}
          onChange={(e) => handleCodeDeviceChange(e.target.value)}
          title="Code u2 脚本在此设备执行"
        >
          {(prerequisites?.devices ?? []).map((d) => (
            <option key={`code-${d.serial}`} value={d.serial} disabled={d.serial === positionSerial}>
              Code · {d.model || d.serial.slice(-8)} ({d.serial.slice(-6)})
            </option>
          ))}
        </select>
        <button
          className="platform-btn platform-btn-primary"
          type="button"
          disabled={!canGenerate || generating}
          onClick={() => void handleGenerate()}
        >
          {generating ? "生成中" : "开始"}
        </button>
        {selectedCaseId && (
          <Link className="platform-btn" to={`/agent/execute/${selectedCaseId}`}>
            执行
          </Link>
        )}
        <div
          className={`dual-gen-status ${prerequisites?.ready ? "ok" : "warn"}`}
          title={prerequisites?.message}
        >
          {prerequisites?.ready
            ? `双路径并行 · Pos ${positionSerial.slice(-6)} · Code ${codeSerial.slice(-6)}`
            : `${prerequisites?.device_count ?? 0}/2 台 · ${prerequisites?.message ?? "检测中"}`}
          {progressText ? ` · ${progressText}` : ""}
        </div>
      </div>

      {error && (
        <div className="platform-error" style={{ marginBottom: 8, padding: "8px 10px" }}>
          {error}
        </div>
      )}

      <div className="dual-gen-split">
        <PathColumn
          title="Position"
          tint="#3b82f6"
          steps={positionSteps}
          viewStep={positionViewStep}
          viewOrder={positionViewOrder}
          activeOrder={positionActiveOrder}
          liveSerial={positionSerial || positionViewStep?.serial}
          liveExpanded={positionLiveExpanded}
          onToggleLive={() => setPositionLiveExpanded((v) => !v)}
          logLine={positionLog}
          showAnnotated
          stepRefs={positionStepRefs}
          onSelectStep={(order) => {
            setPositionSelectedOrder(order);
            scrollPathStep("position", order);
          }}
        />
        <PathColumn
          title="Code"
          tint="#10b981"
          steps={codeSteps}
          viewStep={codeViewStep}
          viewOrder={codeViewOrder}
          activeOrder={codeActiveOrder}
          liveSerial={codeSerial || codeViewStep?.serial}
          liveExpanded={codeLiveExpanded}
          onToggleLive={() => setCodeLiveExpanded((v) => !v)}
          logLine={codeLog}
          stepRefs={codeStepRefs}
          onSelectStep={(order) => {
            setCodeSelectedOrder(order);
            scrollPathStep("code", order);
          }}
        />
      </div>
    </div>
  );
}

function PathColumn({
  title,
  tint,
  steps,
  viewStep,
  viewOrder,
  activeOrder,
  liveSerial,
  liveExpanded,
  onToggleLive,
  logLine,
  showAnnotated,
  stepRefs,
  onSelectStep,
}: {
  title: string;
  tint: string;
  steps: PathStepLive[];
  viewStep: PathStepLive | null;
  viewOrder: number | null;
  activeOrder: number | null;
  liveSerial?: string | null;
  liveExpanded: boolean;
  onToggleLive: () => void;
  logLine: string;
  showAnnotated?: boolean;
  stepRefs: React.MutableRefObject<Map<number, HTMLButtonElement>>;
  onSelectStep: (order: number) => void;
}) {
  const beforeSrc =
    showAnnotated && viewStep?.beforeAnnotated ? viewStep.beforeAnnotated : viewStep?.beforeImage;

  return (
    <div className="dual-gen-column">
      <div className="dual-gen-column-head" style={{ borderColor: tint }}>
        <strong style={{ color: tint }}>{title}</strong>
        <span>{liveSerial ?? "—"}</span>
      </div>

      <div className="dual-gen-column-body">
        <div className="dual-gen-steps">
          {steps.map((step) => (
            <button
              key={step.stepOrder}
              ref={(el) => {
                if (el) stepRefs.current.set(step.stepOrder, el);
                else stepRefs.current.delete(step.stepOrder);
              }}
              type="button"
              className={`dual-gen-step-item ${viewOrder === step.stepOrder ? "active" : ""} ${activeOrder === step.stepOrder ? "running" : ""}`}
              onClick={() => onSelectStep(step.stepOrder)}
            >
              <div className="dual-gen-step-meta">
                <span className={`dual-gen-dot ${step.status}`} />
                <span>#{step.stepOrder + 1}</span>
                {step.isAssertion && <span className="dual-gen-assertion-tag">断言</span>}
                <span>{step.status}</span>
              </div>
              {step.description.slice(0, 36) || "—"}
            </button>
          ))}
        </div>

        <div className="dual-gen-column-main">
          {viewStep && (
            <div className="dual-gen-nl">{viewStep.description || "（无描述）"}</div>
          )}

          <div className={`dual-gen-panel ${liveExpanded ? "" : "live-collapsed"}`}>
            <div className="dual-gen-record">
              <div className="dual-gen-shots">
                <div className="dual-gen-shot">
                  <label>{showAnnotated ? "执行前（标注）" : "执行前"}</label>
                  {beforeSrc ? (
                    <img src={beforeSrc} alt={`${title} before`} />
                  ) : (
                    <div className="dual-gen-shot-empty">等待截图</div>
                  )}
                </div>
                <div className="dual-gen-shot">
                  <label>执行后</label>
                  {viewStep?.afterImage ? (
                    <img src={viewStep.afterImage} alt={`${title} after`} />
                  ) : (
                    <div className="dual-gen-shot-empty">等待执行</div>
                  )}
                </div>
              </div>
              <div className="dual-gen-script">
                <label>生成标准</label>
                <pre>{viewStep?.scriptText ?? "—"}</pre>
              </div>
            </div>

            <div className="dual-gen-live-wrap">
              <button className="dual-gen-live-toggle" type="button" onClick={onToggleLive}>
                <span>实时画面</span>
                <span>{liveExpanded ? "▾ 收起" : "▸ 展开"}</span>
              </button>
              {liveExpanded && <DeviceLiveMirror serial={liveSerial ?? undefined} active={liveExpanded} />}
            </div>
          </div>

          {logLine && <div className="dual-gen-log">{logLine}</div>}
        </div>
      </div>
    </div>
  );
}
