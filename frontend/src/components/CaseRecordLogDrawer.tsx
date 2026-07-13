import { useEffect, useMemo, useState } from "react";
import { caseRecordingApi, type RecordingLogItem } from "../api/caseRecording";
import "./CaseRecordLogDrawer.css";

const LOG_LABEL: Record<string, string> = {
  session: "会话",
  capture: "录制",
  generate_start: "生成开始",
  step_start: "步骤开始",
  llm_input: "LLM 输入",
  llm_output: "LLM 输出",
  step_result: "步骤结果",
  llm_skip: "LLM 跳过",
  llm_parse_error: "解析失败",
  llm_error: "LLM 错误",
  generate_done: "生成完成",
  error: "错误",
};

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function detailBlocks(log: RecordingLogItem): { label: string; content: string }[] {
  const detail = log.detail;
  if (!detail) return [];

  if (log.log_type === "llm_input") {
    const blocks: { label: string; content: string }[] = [];
    if (typeof detail.system_prompt === "string") {
      blocks.push({ label: "System Prompt", content: detail.system_prompt });
    }
    if (typeof detail.user_message === "string") {
      blocks.push({ label: "User Message", content: detail.user_message });
    }
    return blocks;
  }

  if (log.log_type === "llm_output" && typeof detail.raw_response === "string") {
    return [{ label: "Raw Response", content: detail.raw_response }];
  }

  if (log.log_type === "step_result" && typeof detail.description === "string") {
    return [
      {
        label: "生成结果",
        content: JSON.stringify(
          {
            description: detail.description,
            source: detail.source,
            parsed: detail.parsed,
            reason: detail.reason,
            error: detail.error,
          },
          null,
          2
        ),
      },
    ];
  }

  return [{ label: "Detail", content: JSON.stringify(detail, null, 2) }];
}

interface CaseRecordLogDrawerProps {
  sessionUuid: string | null;
  open: boolean;
  onClose: () => void;
  poll?: boolean;
}

export default function CaseRecordLogDrawer({
  sessionUuid,
  open,
  onClose,
  poll = false,
}: CaseRecordLogDrawerProps) {
  const [logs, setLogs] = useState<RecordingLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [stepFilter, setStepFilter] = useState<string>("all");

  const loadLogs = async (reset = false) => {
    if (!sessionUuid) return;
    setLoading(true);
    setError(null);
    try {
      const afterId = reset ? 0 : logs.length > 0 ? logs[logs.length - 1].id : 0;
      const resp = await caseRecordingApi.getLogs(sessionUuid, reset ? 0 : afterId);
      if (reset) {
        setLogs(resp.items);
      } else if (afterId > 0) {
        setLogs((prev) => {
          const seen = new Set(prev.map((item) => item.id));
          const merged = [...prev];
          for (const item of resp.items) {
            if (!seen.has(item.id)) merged.push(item);
          }
          return merged;
        });
      } else {
        setLogs(resp.items);
      }
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载日志失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open || !sessionUuid) return;
    void loadLogs(true);
  }, [open, sessionUuid]);

  useEffect(() => {
    if (!open || !sessionUuid || !poll) return;
    const timer = window.setInterval(() => {
      void loadLogs(false);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [open, sessionUuid, poll, logs.length]);

  const grouped = useMemo(() => {
    const map = new Map<string, RecordingLogItem[]>();
    for (const log of logs) {
      const key = log.step_order == null ? "global" : String(log.step_order);
      const bucket = map.get(key) ?? [];
      bucket.push(log);
      map.set(key, bucket);
    }
    return map;
  }, [logs]);

  const stepKeys = useMemo(() => {
    const keys = Array.from(grouped.keys()).filter((k) => k !== "global");
    keys.sort((a, b) => Number(a) - Number(b));
    return keys;
  }, [grouped]);

  const visibleLogs = useMemo(() => {
    if (stepFilter === "all") return logs;
    if (stepFilter === "global") return grouped.get("global") ?? [];
    return grouped.get(stepFilter) ?? [];
  }, [logs, grouped, stepFilter]);

  const selected = visibleLogs.find((log) => log.id === selectedId) ?? visibleLogs[visibleLogs.length - 1] ?? null;

  if (!open) return null;

  return (
    <div className="case-record-log-backdrop" onClick={onClose}>
      <aside className="case-record-log-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="case-record-log-header">
          <div>
            <div className="case-record-log-kicker">Generation Logs</div>
            <h3>录制与生成日志</h3>
            <p>查看每步 LLM 输入、输出及生成结果</p>
          </div>
          <div className="case-record-log-header-actions">
            <button className="platform-btn" type="button" disabled={loading} onClick={() => void loadLogs(true)}>
              刷新
            </button>
            <button className="platform-btn" type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        </header>

        <div className="case-record-log-toolbar">
          <select
            className="platform-input"
            value={stepFilter}
            onChange={(e) => {
              setStepFilter(e.target.value);
              setSelectedId(null);
            }}
          >
            <option value="all">全部 ({total})</option>
            <option value="global">全局</option>
            {stepKeys.map((key) => (
              <option key={key} value={key}>
                步骤 {Number(key) + 1}
              </option>
            ))}
          </select>
          {poll && <span className="case-record-log-live">实时更新中</span>}
        </div>

        {error && <div className="case-record-log-error">{error}</div>}

        <div className="case-record-log-body">
          <ul className="case-record-log-list">
            {visibleLogs.length === 0 ? (
              <li className="case-record-log-empty">{loading ? "加载中…" : "暂无日志"}</li>
            ) : (
              visibleLogs.map((log) => (
                <li key={log.id}>
                  <button
                    type="button"
                    className={`case-record-log-item ${selected?.id === log.id ? "active" : ""}`}
                    onClick={() => setSelectedId(log.id)}
                  >
                    <div className="case-record-log-item-head">
                      <span className={`case-record-log-type type-${log.log_type}`}>
                        {LOG_LABEL[log.log_type] ?? log.log_type}
                      </span>
                      {log.step_order != null && (
                        <span className="case-record-log-step">步骤 {log.step_order + 1}</span>
                      )}
                      <span className="case-record-log-time">{formatTime(log.created_at)}</span>
                    </div>
                    <div className="case-record-log-message">{log.message}</div>
                  </button>
                </li>
              ))
            )}
          </ul>

          <div className="case-record-log-detail">
            {!selected ? (
              <div className="case-record-log-detail-empty">选择一条日志查看详情</div>
            ) : (
              <>
                <div className="case-record-log-detail-head">
                  <span className={`case-record-log-type type-${selected.log_type}`}>
                    {LOG_LABEL[selected.log_type] ?? selected.log_type}
                  </span>
                  <span className="case-record-log-time">{formatTime(selected.created_at)}</span>
                </div>
                <h4>{selected.message}</h4>
                {detailBlocks(selected).map((block) => (
                  <div key={block.label} className="case-record-log-block">
                    <div className="case-record-log-block-label">{block.label}</div>
                    <pre className="case-record-log-pre">{block.content}</pre>
                  </div>
                ))}
                {detailBlocks(selected).length === 0 && selected.detail && (
                  <pre className="case-record-log-pre">{JSON.stringify(selected.detail, null, 2)}</pre>
                )}
              </>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
