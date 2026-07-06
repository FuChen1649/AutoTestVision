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

interface PathLive {
  serial?: string;
  beforeImage?: string;
  beforeAnnotated?: string;
  afterImage?: string;
  scriptText?: string;
}

interface StepLive {
  stepOrder: number;
  description: string;
  status: StepStatus;
  position: PathLive;
  code: PathLive;
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

function stepFromApi(step: CaseScriptsResponse["steps"][0]): StepLive {
  return {
    stepOrder: step.step_order,
    description: step.description,
    status: (step.script_status as StepStatus) ?? "pending",
    position: {
      scriptText: step.position_script
        ? formatPositionScript(step.position_script as Record<string, unknown>)
        : undefined,
    },
    code: {
      scriptText: step.code_script
        ? formatCodeScript(step.code_script as Record<string, unknown>)
        : undefined,
    },
  };
}

function emptySteps(descriptions: { step_order: number; description: string }[]): StepLive[] {
  return descriptions.map((s) => ({
    stepOrder: s.step_order,
    description: s.description,
    status: "pending",
    position: {},
    code: {},
  }));
}

export default function AgentGeneratePage() {
  const { caseId: caseIdParam } = useParams();
  const navigate = useNavigate();
  const stopStreamRef = useRef<(() => void) | null>(null);
  const stepItemRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

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
  const [liveSteps, setLiveSteps] = useState<StepLive[]>([]);
  const [selectedStepOrder, setSelectedStepOrder] = useState<number | null>(null);
  const [activeStepOrder, setActiveStepOrder] = useState<number | null>(null);
  const [logLine, setLogLine] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [liveExpanded, setLiveExpanded] = useState(true);

  const scrollStepIntoView = useCallback((stepOrder: number) => {
    const el = stepItemRefs.current.get(stepOrder);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const advanceToNextStep = useCallback(
    (completedOrder: number) => {
      setLiveSteps((prev) => {
        const idx = prev.findIndex((s) => s.stepOrder === completedOrder);
        const next = idx >= 0 ? prev[idx + 1] : undefined;
        if (next) {
          window.setTimeout(() => {
            setSelectedStepOrder(next.stepOrder);
            scrollStepIntoView(next.stepOrder);
          }, 200);
        }
        return prev;
      });
    },
    [scrollStepIntoView]
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
      setLiveSteps(data.steps.map(stepFromApi));
      setSelectedStepOrder((current) => current ?? data.steps[0]?.step_order ?? null);
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

  const updateStep = useCallback((stepOrder: number, updater: (step: StepLive) => StepLive) => {
    setLiveSteps((prev) =>
      prev.map((s) => (s.stepOrder === stepOrder ? updater(s) : s))
    );
  }, []);

  const applyStreamEvent = useCallback(
    (event: Record<string, unknown>) => {
      const name = String(event.event ?? "");
      const stepOrder = event.step_order != null ? Number(event.step_order) : null;
      const detail = (event.detail ?? {}) as Record<string, unknown>;
      const message = String(event.message ?? "");

      setLogLine(message || name);

      if (stepOrder == null) {
        if (name === "started") {
          const pos = detail.position_serial ? String(detail.position_serial) : "";
          const code = detail.code_serial ? String(detail.code_serial) : "";
          if (pos) setPositionSerial(pos);
          if (code) setCodeSerial(code);
        }
        if (name === "completed" || name === "error" || name === "cancelled") {
          setGenerating(false);
          setActiveStepOrder(null);
        }
        return;
      }

      setActiveStepOrder(stepOrder);
      if (name !== "step_executed") {
        setSelectedStepOrder(stepOrder);
        scrollStepIntoView(stepOrder);
      }

      if (name === "step_start") {
        updateStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          position: { ...s.position, serial: positionSerial || s.position.serial },
          code: { ...s.code, serial: codeSerial || s.code.serial },
        }));
      }

      if (name === "capture_before") {
        const pos = detail.position as Record<string, unknown> | undefined;
        const code = detail.code as Record<string, unknown> | undefined;
        updateStep(stepOrder, (s) => ({
          ...s,
          position: {
            ...s.position,
            serial: String(pos?.serial ?? s.position.serial ?? ""),
            beforeImage: String(pos?.before_image ?? s.position.beforeImage ?? ""),
          },
          code: {
            ...s.code,
            serial: String(code?.serial ?? s.code.serial ?? ""),
            beforeImage: String(code?.before_image ?? s.code.beforeImage ?? ""),
          },
        }));
      }

      if (name === "scripts_ready") {
        const pos = detail.position as Record<string, unknown> | undefined;
        const code = detail.code as Record<string, unknown> | undefined;
        updateStep(stepOrder, (s) => ({
          ...s,
          status: "generating",
          position: {
            ...s.position,
            beforeImage: String(pos?.before_image ?? s.position.beforeImage ?? ""),
            beforeAnnotated: String(pos?.before_image_annotated ?? s.position.beforeAnnotated ?? ""),
            scriptText: formatPositionScript(pos?.script as Record<string, unknown>),
          },
          code: {
            ...s.code,
            beforeImage: String(code?.before_image ?? s.code.beforeImage ?? ""),
            scriptText: formatCodeScript(code?.script as Record<string, unknown>),
          },
        }));
      }

      if (name === "step_executed") {
        const pos = detail.position as Record<string, unknown> | undefined;
        const code = detail.code as Record<string, unknown> | undefined;
        const posExecError = pos?.exec_error ? String(pos.exec_error) : null;
        const codeExecError = code?.exec_error ? String(code.exec_error) : null;
        const codeScript = code?.script as Record<string, unknown> | undefined;
        updateStep(stepOrder, (s) => ({
          ...s,
          status: "ready",
          position: {
            ...s.position,
            serial: String(pos?.serial ?? s.position.serial ?? ""),
            afterImage: String(pos?.after_image ?? s.position.afterImage ?? ""),
            scriptText: posExecError
              ? `${s.position.scriptText ?? "—"}\n\n⚠ 执行失败:\n${posExecError.slice(0, 400)}`
              : s.position.scriptText,
          },
          code: {
            ...s.code,
            serial: String(code?.serial ?? s.code.serial ?? ""),
            afterImage: String(code?.after_image ?? s.code.afterImage ?? ""),
            scriptText: codeExecError
              ? `${s.code.scriptText ?? formatCodeScript(codeScript)}\n\n⚠ 执行失败:\n${codeExecError.slice(0, 400)}`
              : s.code.scriptText ?? (codeScript ? formatCodeScript(codeScript) : undefined),
          },
        }));
        advanceToNextStep(stepOrder);
      }

      if (name === "error") {
        updateStep(stepOrder, (s) => ({ ...s, status: "failed" }));
        setGenerating(false);
        setActiveStepOrder(null);
        setError(message || "生成失败");
      }
    },
    [advanceToNextStep, codeSerial, positionSerial, scrollStepIntoView, updateStep]
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
    setLogLine("启动生成…");
    stopStreamRef.current?.();
    setLiveSteps(emptySteps(scripts.steps.map((s) => ({ step_order: s.step_order, description: s.description }))));
    const firstOrder = scripts.steps[0]?.step_order;
    if (firstOrder != null) {
      setSelectedStepOrder(firstOrder);
      window.setTimeout(() => scrollStepIntoView(firstOrder), 100);
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

  const viewStepOrder = selectedStepOrder ?? activeStepOrder ?? liveSteps[0]?.stepOrder ?? null;
  const viewStep = useMemo(
    () => liveSteps.find((s) => s.stepOrder === viewStepOrder) ?? null,
    [liveSteps, viewStepOrder]
  );

  const progressText = generating && activeStepOrder != null
    ? `正在生成步骤 ${activeStepOrder + 1} / ${liveSteps.length}`
    : scripts?.script_status
      ? `脚本状态 · ${scripts.script_status}`
      : "";

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
            ? `双设备并行 · Pos ${positionSerial.slice(-6)} · Code ${codeSerial.slice(-6)}`
            : `${prerequisites?.device_count ?? 0}/2 台 · ${prerequisites?.message ?? "检测中"}`}
          {progressText ? ` · ${progressText}` : ""}
        </div>
        <button
          className="platform-btn"
          type="button"
          onClick={() => setLiveExpanded((v) => !v)}
          title={liveExpanded ? "收起实时画面，腾出步骤区域" : "展开实时画面"}
        >
          {liveExpanded ? "收起实时" : "展开实时"}
        </button>
      </div>

      {error && <div className="platform-error" style={{ marginBottom: 8, padding: "8px 10px" }}>{error}</div>}

      <div className="dual-gen-layout">
        <div className="dual-gen-steps">
          {liveSteps.map((step) => (
            <button
              key={step.stepOrder}
              ref={(el) => {
                if (el) stepItemRefs.current.set(step.stepOrder, el);
                else stepItemRefs.current.delete(step.stepOrder);
              }}
              type="button"
              className={`dual-gen-step-item ${viewStepOrder === step.stepOrder ? "active" : ""} ${activeStepOrder === step.stepOrder ? "running" : ""}`}
              onClick={() => {
                setSelectedStepOrder(step.stepOrder);
                scrollStepIntoView(step.stepOrder);
              }}
            >
              <div className="dual-gen-step-meta">
                <span className={`dual-gen-dot ${step.status}`} />
                <span>#{step.stepOrder + 1}</span>
                <span>{step.status}</span>
              </div>
              {step.description.slice(0, 36) || "—"}
            </button>
          ))}
        </div>

        <div className="dual-gen-main">
          {viewStep && (
            <div className="dual-gen-nl">{viewStep.description || "（无描述）"}</div>
          )}

          <div className="dual-gen-panels">
            <DevicePanel
              title="Position"
              tint="#3b82f6"
              path={viewStep?.position}
              liveSerial={positionSerial || viewStep?.position.serial}
              liveExpanded={liveExpanded}
              onToggleLive={() => setLiveExpanded((v) => !v)}
              showAnnotated
            />
            <DevicePanel
              title="Code"
              tint="#10b981"
              path={viewStep?.code}
              liveSerial={codeSerial || viewStep?.code.serial}
              liveExpanded={liveExpanded}
              onToggleLive={() => setLiveExpanded((v) => !v)}
            />
          </div>

          {logLine && <div className="dual-gen-log">{logLine}</div>}
        </div>
      </div>
    </div>
  );
}

function DevicePanel({
  title,
  tint,
  path,
  liveSerial,
  liveExpanded,
  onToggleLive,
  showAnnotated,
}: {
  title: string;
  tint: string;
  path?: PathLive;
  liveSerial?: string | null;
  liveExpanded: boolean;
  onToggleLive: () => void;
  showAnnotated?: boolean;
}) {
  const beforeSrc = showAnnotated && path?.beforeAnnotated ? path.beforeAnnotated : path?.beforeImage;

  return (
    <div className={`dual-gen-panel ${liveExpanded ? "" : "live-collapsed"}`}>
      <div className="dual-gen-panel-head">
        <strong style={{ color: tint }}>{title}</strong>
        <span>{liveSerial ?? path?.serial ?? "—"}</span>
      </div>

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
            {path?.afterImage ? (
              <img src={path.afterImage} alt={`${title} after`} />
            ) : (
              <div className="dual-gen-shot-empty">等待执行</div>
            )}
          </div>
        </div>
        <div className="dual-gen-script">
          <label>生成标准</label>
          <pre>{path?.scriptText ?? "—"}</pre>
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
  );
}
