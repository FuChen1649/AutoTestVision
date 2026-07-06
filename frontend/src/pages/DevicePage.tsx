import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { DeviceInfo } from "../types";
import "./PlatformPages.css";

export default function DevicePage() {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.listDevices();
      setDevices(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载设备失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <div className="platform-page">
      <div className="platform-page-header">
        <h2>设备管理</h2>
        <button className="platform-btn" type="button" onClick={() => void refresh()}>
          刷新
        </button>
      </div>

      <div className="platform-card">
        <h3>ADB 设备列表</h3>
        <p style={{ marginTop: 8 }}>
          完整设备管理能力（分组、标签、远程 farm）将在后续迭代提供。当前可通过 Case 构建页的设备面板进行屏幕镜像与操作。
        </p>
      </div>

      {error && <div className="platform-error">{error}</div>}

      <div className="platform-table-wrap">
        <table className="platform-table">
          <thead>
            <tr>
              <th>Serial</th>
              <th>型号</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((d) => (
              <tr key={d.serial}>
                <td>{d.serial}</td>
                <td>{d.model ?? "—"}</td>
                <td>{d.connected ? "已连接" : "离线"}</td>
                <td>
                  <button
                    className="platform-link-btn"
                    type="button"
                    onClick={() => void api.selectDevice(d.serial)}
                  >
                    设为当前设备
                  </button>
                </td>
              </tr>
            ))}
            {!loading && devices.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="platform-empty">未检测到 ADB 设备，请确认 adb devices 可见</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
