import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { AppInfo, AppPermissionInfo, DeviceInfo } from "../types";

interface AppPermissionControlsProps {
  devices: DeviceInfo[];
  serial: string | null;
  onSelectDevice: (serial: string) => void;
  onMessage: (message: string | null) => void;
  onPermissionPresetAdded: () => void;
}

function categoryPrefix(category: string) {
  if (category === "system") {
    return "[系统] ";
  }
  if (category === "common") {
    return "[常用] ";
  }
  return "";
}

export default function AppPermissionControls({
  devices,
  serial,
  onSelectDevice,
  onMessage,
  onPermissionPresetAdded,
}: AppPermissionControlsProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  const [apps, setApps] = useState<AppInfo[]>([]);
  const [permissions, setPermissions] = useState<AppPermissionInfo[]>([]);
  const [selectedPackage, setSelectedPackage] = useState("");
  const [selectedPermissions, setSelectedPermissions] = useState<Set<string>>(new Set());
  const [loadingApps, setLoadingApps] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [applying, setApplying] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const revocablePermissions = useMemo(
    () => permissions.filter((item) => item.revocable),
    [permissions]
  );

  const allRevocableSelected =
    revocablePermissions.length > 0 &&
    revocablePermissions.every((item) => selectedPermissions.has(item.name));

  useEffect(() => {
    if (!serial) {
      setApps([]);
      setPermissions([]);
      setSelectedPackage("");
      setSelectedPermissions(new Set());
      return;
    }

    setLoadingApps(true);
    onMessage(null);
    void api
      .listApps(serial)
      .then((list) => {
        setApps(list);
        setSelectedPackage((current) => {
          if (current && list.some((app) => app.package === current)) {
            return current;
          }
          return list[0]?.package ?? "";
        });
      })
      .catch((err) => {
        setApps([]);
        setSelectedPackage("");
        onMessage(err instanceof Error ? err.message : "加载应用列表失败");
      })
      .finally(() => setLoadingApps(false));
  }, [serial, onMessage]);

  useEffect(() => {
    if (!serial || !selectedPackage) {
      setPermissions([]);
      setSelectedPermissions(new Set());
      return;
    }

    setLoadingPermissions(true);
    void api
      .getAppPermissions(selectedPackage, serial)
      .then((list) => {
        setPermissions(list);
        const granted = new Set(
          list.filter((item) => item.granted).map((item) => item.name)
        );
        setSelectedPermissions(granted);
      })
      .catch((err) => {
        setPermissions([]);
        setSelectedPermissions(new Set());
        onMessage(err instanceof Error ? err.message : "加载权限失败");
      })
      .finally(() => setLoadingPermissions(false));
  }, [serial, selectedPackage, onMessage]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const togglePermission = (name: string) => {
    setSelectedPermissions((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (allRevocableSelected) {
      setSelectedPermissions((prev) => {
        const next = new Set(prev);
        revocablePermissions.forEach((item) => next.delete(item.name));
        return next;
      });
      return;
    }

    setSelectedPermissions((prev) => {
      const next = new Set(prev);
      revocablePermissions.forEach((item) => next.add(item.name));
      return next;
    });
  };

  const handleApply = async () => {
    if (!serial || !selectedPackage) {
      return;
    }

    setApplying(true);
    onMessage(null);
    try {
      const result = await api.applyAppPermissions(
        selectedPackage,
        Array.from(selectedPermissions),
        serial
      );

      const refreshed = await api.getAppPermissions(selectedPackage, serial);
      setPermissions(refreshed);
      setSelectedPermissions(
        new Set(refreshed.filter((item) => item.granted).map((item) => item.name))
      );

      const summary = [
        result.granted.length > 0 ? `已授予 ${result.granted.length} 项` : "",
        result.revoked.length > 0 ? `已撤销 ${result.revoked.length} 项` : "",
        result.skipped.length > 0 ? `${result.skipped.length} 项不可变更` : "",
        result.errors.length > 0 ? `${result.errors.length} 项失败` : "",
      ]
        .filter(Boolean)
        .join("，");

      onPermissionPresetAdded();
      onMessage(summary || "权限已重置");
    } catch (err) {
      onMessage(err instanceof Error ? err.message : "权限重置失败");
    } finally {
      setApplying(false);
      setMenuOpen(false);
    }
  };

  const permissionSummary =
    permissions.length === 0
      ? "权限"
      : `权限 ${selectedPermissions.size}/${permissions.length}`;

  return (
    <div className="device-toolbar">
      <select
        className="toolbar-control toolbar-select"
        value={serial ?? ""}
        onChange={(event) => onSelectDevice(event.target.value)}
        title="选择设备"
      >
        <option value="" disabled>
          设备
        </option>
        {devices.map((device) => (
          <option key={device.serial} value={device.serial}>
            {device.model || device.product || device.serial}
          </option>
        ))}
      </select>

      <select
        className="toolbar-control toolbar-select"
        value={selectedPackage}
        disabled={!serial || loadingApps}
        onChange={(event) => setSelectedPackage(event.target.value)}
        title="选择应用"
      >
        <option value="" disabled>
          {loadingApps ? "应用..." : "应用"}
        </option>
        {apps.map((app) => (
          <option key={app.package} value={app.package}>
            {categoryPrefix(app.category)}
            {app.label}
          </option>
        ))}
      </select>

      <div className="permission-dropdown toolbar-control" ref={menuRef}>
        <button
          className="permission-dropdown-trigger toolbar-select"
          type="button"
          disabled={!selectedPackage || loadingPermissions || permissions.length === 0}
          onClick={() => setMenuOpen((open) => !open)}
          title={permissionSummary}
        >
          {loadingPermissions ? "权限..." : permissionSummary}
        </button>

        {menuOpen && permissions.length > 0 && (
          <div className="permission-dropdown-menu">
            <label className="permission-option permission-option-all">
              <input
                type="checkbox"
                checked={allRevocableSelected}
                onChange={handleSelectAll}
              />
              <span>全选可变更权限</span>
            </label>
            <div className="permission-option-list">
              {permissions.map((permission) => (
                <label
                  key={permission.name}
                  className={
                    permission.revocable
                      ? "permission-option"
                      : "permission-option permission-option-fixed"
                  }
                  title={permission.name}
                >
                  <input
                    type="checkbox"
                    checked={selectedPermissions.has(permission.name)}
                    disabled={!permission.revocable}
                    onChange={() => togglePermission(permission.name)}
                  />
                  <span>
                    {permission.label}
                    {permission.granted ? " · 已授予" : " · 未授予"}
                    {!permission.revocable ? " · 不可变更" : ""}
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      <button
        className="permission-reset-btn toolbar-reset"
        type="button"
        disabled={!selectedPackage || applying || permissions.length === 0}
        onClick={() => void handleApply()}
      >
        {applying ? "..." : "重置"}
      </button>
    </div>
  );
}
