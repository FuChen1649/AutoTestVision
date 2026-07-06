import { useEffect, useState } from "react";
import { createScreenStream } from "../api/client";
import type { ScreenFrame } from "../types";

interface DeviceLiveMirrorProps {
  serial?: string;
  active?: boolean;
}

/** 只读设备实时画面（WebSocket 镜像） */
export default function DeviceLiveMirror({ serial, active = true }: DeviceLiveMirrorProps) {
  const [image, setImage] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!serial || !active) {
      setImage(null);
      setConnected(false);
      return;
    }

    const socket = createScreenStream(serial, 5);

    socket.onopen = () => setConnected(true);
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as ScreenFrame;
      if (data.type === "error") {
        setConnected(false);
        return;
      }
      if (data.image) {
        setImage(data.image.startsWith("data:") ? data.image : `data:image/png;base64,${data.image}`);
        setConnected(true);
      }
    };
    socket.onerror = () => setConnected(false);
    socket.onclose = () => setConnected(false);

    return () => socket.close();
  }, [serial, active]);

  if (!serial) {
    return <div className="dual-gen-live-empty">未绑定设备</div>;
  }

  return (
    <div className="dual-gen-live-viewport">
      {image ? (
        <img src={image} alt={`live ${serial}`} className="dual-gen-live-img" />
      ) : (
        <div className="dual-gen-live-empty">{connected ? "等待帧…" : "连接中…"}</div>
      )}
      <span className={`dual-gen-live-badge ${connected ? "on" : "off"}`}>
        {connected ? "LIVE" : "OFF"}
      </span>
    </div>
  );
}
