import { useMemo, useState } from "react";
import { api } from "../api/client";

interface ScreenLayout {
  offsetX: number;
  offsetY: number;
  width: number;
  height: number;
}

interface DeviceNavKeysProps {
  serial: string | null;
  viewportWidth: number;
  layout: ScreenLayout;
  disabled?: boolean;
  onError?: (message: string | null) => void;
  onKeyPress?: (key: NavKey) => Promise<void>;
}

type NavKey = "back" | "home" | "recents";

const NAV_ITEMS: { key: NavKey; label: string; title: string }[] = [
  { key: "back", label: "Back", title: "返回 (BACK)" },
  { key: "home", label: "Home", title: "主屏 (HOME)" },
  { key: "recents", label: "Recents", title: "最近任务 / 后台应用" },
];

function NavKeyIcon({ kind }: { kind: NavKey }) {
  if (kind === "back") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === "home") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path
          d="M5 11.5V19a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-7.5M4 10.5L12 4l8 6.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <rect x="4" y="5" width="11" height="14" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="9" y="5" width="11" height="14" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export default function DeviceNavKeys({
  serial,
  viewportWidth,
  layout,
  disabled = false,
  onError,
  onKeyPress,
}: DeviceNavKeysProps) {
  const [pressing, setPressing] = useState<NavKey | null>(null);

  const placement = useMemo(() => {
    if (layout.width <= 0 || layout.height <= 0) {
      return null;
    }

    const btnSize = Math.round(Math.min(44, Math.max(26, layout.height * 0.065)));
    const gap = Math.max(4, Math.round(btnSize * 0.18));
    const gutterRight = Math.max(0, viewportWidth - layout.offsetX - layout.width);
    const fitsGutter = gutterRight >= btnSize + 6;
    const left = fitsGutter
      ? layout.offsetX + layout.width + Math.max(4, (gutterRight - btnSize) / 2)
      : layout.offsetX + layout.width - btnSize - 6;

    return {
      btnSize,
      gap,
      top: layout.offsetY,
      left,
      overlay: !fitsGutter,
    };
  }, [layout, viewportWidth]);

  if (!placement || !serial) {
    return null;
  }

  const handlePress = async (key: NavKey) => {
    if (disabled || pressing) {
      return;
    }
    setPressing(key);
    try {
      if (onKeyPress) {
        await onKeyPress(key);
      } else {
        await api.pressDeviceKey(key, serial);
      }
      onError?.(null);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "按键发送失败");
    } finally {
      setPressing(null);
    }
  };

  return (
    <div
      className={`device-nav-keys ${placement.overlay ? "overlay" : ""}`}
      style={{
        top: placement.top,
        left: placement.left,
        width: placement.btnSize,
        gap: placement.gap,
      }}
    >
      {NAV_ITEMS.map((item) => (
        <button
          key={item.key}
          type="button"
          className={`device-nav-key ${pressing === item.key ? "pressing" : ""}`}
          style={{ width: placement.btnSize, height: placement.btnSize }}
          title={item.title}
          aria-label={item.title}
          disabled={disabled || pressing !== null}
          onClick={() => void handlePress(item.key)}
        >
          <NavKeyIcon kind={item.key} />
        </button>
      ))}
    </div>
  );
}
