import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  caseRecordingApi,
  type GeneratedStepDraft,
  type RecordActionPayload,
  type RecordingSession,
} from "../api/caseRecording";
import { api } from "../api/client";
import DeviceScreen, { type DeviceInteraction } from "../components/DeviceScreen";
import CaseRecordLogDrawer from "../components/CaseRecordLogDrawer";
import type { DeviceInfo } from "../types";
import "./CaseRecordPage.css";

type Phase = "setup" | "recording" | "generating" | "review" | "saved";

function captureLabel(event: RecordingSession["events"][number]) {
  const size =
    event.device_width && event.device_height
      ? ` · ${event.device_width}×${event.device_height}`
      : "";
  const point = (x?: number | null, y?: number | null) =>
    x != null && y != null ? `(${x}, ${y})` : "(—)";

  if (event.action_type === "key") {
    const labels: Record<string, string> = { back: "返回键", home: "主屏键", recents: "最近任务键" };
    return `${labels[event.key_name ?? ""] ?? "系统键"}${size}`;
  }
  if (event.action_type === "swipe") {
    return `滑动 ${point(event.x, event.y)} → ${point(event.x2, event.y2)}${size}`;
  }
  if (event.action_type === "long_press") {
    return `长按 ${point(event.x, event.y)}${size}`;
  }
  return `点击 ${point(event.x, event.y)}${size}`;
}

function toRecordPayload(interaction: DeviceInteraction): RecordActionPayload {
  if (interaction.type === "tap") {
    return { action_type: "tap", x: interaction.x, y: interaction.y };
  }
  if (interaction.type === "long_press") {
    return {
      action_type: "long_press",
      x: interaction.x,
      y: interaction.y,
      duration_ms: interaction.durationMs,
    };
  }
  if (interaction.type === "swipe") {
    return {
      action_type: "swipe",
      x: interaction.x1,
      y: interaction.y1,
      x2: interaction.x2,
      y2: interaction.y2,
      duration_ms: interaction.durationMs,
    };
  }
  return { action_type: "key", key: interaction.key };
}

export default function CaseRecordPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("setup");
  const [caseName, setCaseName] = useState("录制 Case");
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [providers, setProviders] = useState<{ id: string; label: string; available: boolean }[]>([]);
  const [session, setSession] = useState<RecordingSession | null>(null);
  const [draftSteps, setDraftSteps] = useState<GeneratedStepDraft[]>([]);
  const [savedCaseId, setSavedCaseId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [logOpen, setLogOpen] = useState(false);

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
        const next =
          current && list.some((d) => d.serial === current) ? current : list[0].serial;
        if (next !== current) {
          setSelectedSerial(next);
          selectedSerialRef.current = next;
        }
        if (next) {
          await api.selectDevice(next);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "设备列表加载失败");
    } finally {
      setDeviceLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshDevices();
    void caseRecordingApi.listProviders().then((resp) => {
      setProviders(resp.providers);
      const first = resp.providers.find((p) => p.available);
      if (first) setLlmProvider(first.id);
    });
  }, [refreshDevices]);

  const handleStart = async () => {
    if (!selectedSerial) {
      setError("请先连接并选择设备");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await caseRecordingApi.createSession({
        serial: selectedSerial,
        case_name: caseName.trim() || "录制 Case",
        llm_provider: llmProvider || null,
      });
      setSession(created);
      setPhase("recording");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建录制会话失败");
    } finally {
      setBusy(false);
    }
  };

  const handleInteraction = useCallback(
    async (interaction: DeviceInteraction) => {
      if (!session || phase !== "recording" || actionBusy) return;
      setActionBusy(true);
      setError(null);
      try {
        const updated = await caseRecordingApi.recordAction(
          session.session_uuid,
          toRecordPayload(interaction)
        );
        setSession(updated);
      } catch (err) {
        setError(err instanceof Error ? err.message : "录制操作失败");
      } finally {
        setActionBusy(false);
      }
    },
    [session, phase, actionBusy]
  );

  const handleStop = async () => {
    if (!session) return;
    setPhase("generating");
    setBusy(true);
    setError(null);
    try {
      const updated = await caseRecordingApi.stopRecording(session.session_uuid);
      setSession(updated);
      setDraftSteps(updated.generated_steps);
      if (updated.status === "failed") {
        setError(updated.error ?? "步骤生成失败，可手动编辑后保存");
        setDraftSteps(
          updated.events.map((event, index) => ({
            step_order: index,
            description: captureLabel(event),
            event_uuid: event.event_uuid,
            screen_image_url: event.before_image_url,
            screen_width: event.device_width,
            screen_height: event.device_height,
            selection_x: event.x,
            selection_y: event.y,
            selection_width: 48,
            selection_height: 48,
          }))
        );
      }
      setPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "结束录制失败");
      setPhase("recording");
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const result = await caseRecordingApi.confirmSave(session.session_uuid, {
        case_name: caseName.trim() || session.case_name,
        steps: draftSteps,
      });
      setSavedCaseId(result.case_id);
      setPhase("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const handleDiscard = async () => {
    if (session) {
      try {
        await caseRecordingApi.deleteSession(session.session_uuid);
      } catch {
        /* ignore */
      }
    }
    setSession(null);
    setDraftSteps([]);
    setPhase("setup");
    setError(null);
  };

  const updateStepDescription = (index: number, description: string) => {
    setDraftSteps((prev) =>
      prev.map((step, i) => (i === index ? { ...step, description } : step))
    );
  };

  return (
    <div className="case-record-page">
      <header className="case-record-header">
        <div>
          <div className="case-record-kicker">Case Recording</div>
          <h2>录制生成 Case</h2>
          <p>在实时手机屏幕上操作，系统自动记录截图与 UI 结构，结束后由 Agent 生成自然语言步骤。</p>
        </div>
        <div className="case-record-header-actions">
          {session && (
            <button className="platform-btn" type="button" onClick={() => setLogOpen(true)}>
              生成日志
            </button>
          )}
          <Link className="platform-btn" to="/cases">
            返回 Case 列表
          </Link>
        </div>
      </header>

      {error && <div className="case-record-error">{error}</div>}

      <div className="case-record-layout">
        <div className="case-record-screen">
          <DeviceScreen
            devices={devices}
            selectedSerial={selectedSerial}
            deviceLoading={deviceLoading}
            onRefreshDevices={() => void refreshDevices()}
            onSelectDevice={(serial) => {
              setSelectedSerial(serial);
              void api.selectDevice(serial);
            }}
            onPermissionPresetAdded={() => {}}
            showNavKeys={phase === "recording"}
            readOnly={phase !== "recording"}
            interactionDisabled={phase !== "recording" || actionBusy || busy}
            onInteraction={phase === "recording" ? handleInteraction : undefined}
          />
          {phase === "recording" && actionBusy && (
            <div className="case-record-action-overlay">正在捕获操作…</div>
          )}
        </div>

        <aside className="case-record-panel">
          {phase === "setup" && (
            <div className="case-record-section">
              <h3>开始录制</h3>
              <label className="case-record-field">
                <span>Case 名称</span>
                <input
                  className="platform-input"
                  value={caseName}
                  onChange={(e) => setCaseName(e.target.value)}
                  placeholder="例如：登录流程"
                />
              </label>
              <label className="case-record-field">
                <span>步骤生成模型</span>
                <select
                  className="platform-input"
                  value={llmProvider}
                  onChange={(e) => setLlmProvider(e.target.value)}
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id} disabled={!p.available}>
                      {p.label}
                      {!p.available ? "（不可用）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <p className="case-record-hint">
                连接设备后点击开始，在左侧屏幕上进行点击、滑动、长按或系统键操作。录制过程中仅记录坐标与截图，自然语言步骤在结束后由 LLM 根据截图生成。
              </p>
              <button
                className="platform-btn platform-btn-primary"
                type="button"
                disabled={busy || !selectedSerial}
                onClick={() => void handleStart()}
              >
                开始录制
              </button>
            </div>
          )}

          {phase === "recording" && session && (
            <div className="case-record-section">
              <div className="case-record-status-row">
                <span className="case-record-badge recording">录制中</span>
                <span className="case-record-count">{session.event_count} 步</span>
              </div>
              <h3>{session.case_name}</h3>
              <ul className="case-record-event-list">
                {session.events.length === 0 ? (
                  <li className="case-record-event-empty">在左侧屏幕操作，将记录坐标与截图</li>
                ) : (
                  session.events.map((event) => (
                    <li key={event.event_uuid} className="case-record-event-item">
                      <span className="case-record-event-no">{event.step_order + 1}</span>
                      <div className="case-record-event-body">
                        <div className="case-record-event-title">{captureLabel(event)}</div>
                        {event.before_image_url && (
                          <img
                            className="case-record-event-thumb"
                            src={event.before_image_url}
                            alt={`步骤 ${event.step_order + 1}`}
                          />
                        )}
                      </div>
                    </li>
                  ))
                )}
              </ul>
              <div className="case-record-actions">
                <button
                  className="platform-btn platform-btn-primary"
                  type="button"
                  disabled={busy || session.event_count === 0}
                  onClick={() => void handleStop()}
                >
                  结束并生成步骤
                </button>
                <button className="platform-btn" type="button" disabled={busy} onClick={() => void handleDiscard()}>
                  放弃
                </button>
              </div>
            </div>
          )}

          {phase === "generating" && (
            <div className="case-record-section case-record-generating">
              <div className="case-record-spinner" />
              <h3>Agent 正在生成自然语言步骤…</h3>
              <p>根据录制的操作序列与 UI 信息反向编写测试步骤。</p>
            </div>
          )}

          {phase === "review" && session && (
            <div className="case-record-section">
              <div className="case-record-status-row">
                <span className="case-record-badge review">待确认</span>
                <span className="case-record-count">{draftSteps.length} 步</span>
              </div>
              <label className="case-record-field">
                <span>Case 名称</span>
                <input
                  className="platform-input"
                  value={caseName}
                  onChange={(e) => setCaseName(e.target.value)}
                />
              </label>
              <ul className="case-record-draft-list">
                {draftSteps.map((step, index) => (
                  <li key={step.event_uuid} className="case-record-draft-item">
                    <span className="case-record-event-no">{index + 1}</span>
                    <div className="case-record-draft-body">
                      {step.screen_image_url && (
                        <img
                          className="case-record-event-thumb"
                          src={step.screen_image_url}
                          alt={`步骤 ${index + 1}`}
                        />
                      )}
                      <textarea
                        className="platform-input case-record-step-input"
                        rows={2}
                        value={step.description}
                        onChange={(e) => updateStepDescription(index, e.target.value)}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              <div className="case-record-actions">
                <button
                  className="platform-btn platform-btn-primary"
                  type="button"
                  disabled={busy || draftSteps.length === 0}
                  onClick={() => void handleSave()}
                >
                  确认保存 Case
                </button>
                <button className="platform-btn" type="button" disabled={busy} onClick={() => void handleDiscard()}>
                  放弃
                </button>
              </div>
            </div>
          )}

          {phase === "saved" && savedCaseId && (
            <div className="case-record-section case-record-saved">
              <h3>Case 已保存</h3>
              <p>共 {draftSteps.length} 个步骤已写入 Case 管理。</p>
              <div className="case-record-actions">
                <button
                  className="platform-btn platform-btn-primary"
                  type="button"
                  onClick={() => navigate(`/cases/${savedCaseId}/edit`)}
                >
                  继续编辑 Case
                </button>
                <Link className="platform-btn" to="/cases">
                  返回列表
                </Link>
              </div>
            </div>
          )}
        </aside>
      </div>

      <CaseRecordLogDrawer
        sessionUuid={session?.session_uuid ?? null}
        open={logOpen}
        onClose={() => setLogOpen(false)}
        poll={phase === "recording" || phase === "generating"}
      />
    </div>
  );
}
