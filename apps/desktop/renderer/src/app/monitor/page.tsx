"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./monitor.module.css";

type MonitorSnapshot = {
  session_id: string;
  profile_id: string;
  active_agent_id: string | null;
  agent_lease_expires_at: string | null;
  tab_id: string;
  document_id: string;
  document_revision: number;
  url: string;
  title: string;
  object_count: number;
  takeover_required: boolean;
  takeover_reason: string | null;
};

type SessionEvent = {
  event_id: string;
  sequence: number;
  session_id: string;
  event_type: string;
  timestamp: string;
  tab_id: string | null;
  document_id: string | null;
  operation_id: string | null;
  data: Record<string, unknown>;
};

type VisualFrameHeader = {
  type: "visual_frame";
  stream_id: string;
  frame_seq: number;
  session_id: string;
  tab_id: string;
  document_id: string;
  format: "jpeg" | "png" | "webp";
  width: number;
  height: number;
  device_scale_factor: number;
  captured_at: string;
};

type ConnectionState = "connecting" | "live" | "disconnected" | "error";

const MAX_EVENTS = 80;

export default function MonitorPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<MonitorSnapshot | null>(null);
  const lastSequenceRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [frameHeader, setFrameHeader] = useState<VisualFrameHeader | null>(null);
  const [frameCount, setFrameCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  const applySnapshot = useCallback((nextSnapshot: MonitorSnapshot) => {
    const previous = snapshotRef.current;
    if (
      previous &&
      (previous.session_id !== nextSnapshot.session_id ||
        previous.tab_id !== nextSnapshot.tab_id ||
        previous.document_id !== nextSnapshot.document_id)
    ) {
      setFrameHeader(null);
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (canvas && context) context.clearRect(0, 0, canvas.width, canvas.height);
    }
    snapshotRef.current = nextSnapshot;
    setSnapshot(nextSnapshot);
  }, []);

  const drawFrame = useCallback(async (packet: ArrayBuffer) => {
    try {
      const view = new DataView(packet);
      if (view.byteLength < 4) throw new Error("视觉帧数据不完整");
      const headerLength = view.getUint32(0, false);
      const headerEnd = 4 + headerLength;
      if (headerLength < 2 || headerEnd > packet.byteLength) {
        throw new Error("视觉帧头部无效");
      }
      const decoder = new TextDecoder();
      const header = JSON.parse(
        decoder.decode(new Uint8Array(packet, 4, headerLength)),
      ) as VisualFrameHeader;
      if (header.type !== "visual_frame") throw new Error("未知视觉帧协议");
      const current = snapshotRef.current;
      if (
        current &&
        (header.session_id !== current.session_id ||
          (current.tab_id && header.tab_id !== current.tab_id) ||
          (current.document_id && header.document_id !== current.document_id))
      ) {
        return;
      }
      const imageBytes = packet.slice(headerEnd);
      const mime = header.format === "jpeg" ? "image/jpeg" : `image/${header.format}`;
      const bitmap = await createImageBitmap(new Blob([imageBytes], { type: mime }));
      setFrameHeader(header);
      setFrameCount((value) => value + 1);
      const canvas = canvasRef.current;
      if (!canvas) {
        bitmap.close();
        return;
      }
      canvas.width = header.width || bitmap.width;
      canvas.height = header.height || bitmap.height;
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) {
        bitmap.close();
        return;
      }
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  const connect = useCallback(async () => {
    if (stoppedRef.current) return;
    setConnectionState("connecting");
    setLastError(null);
    try {
      const config = await window.webfaMonitor?.getConfig();
      if (!config) throw new Error("当前窗口没有 Monitor 权限");
      const socket = new WebSocket(config.websocketUrl);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      socket.onopen = () => {
        socket.send(JSON.stringify({
          type: "authenticate",
          token: config.token,
          after_sequence: lastSequenceRef.current,
          stream: {
            format: "jpeg",
            quality: 72,
            max_width: 1440,
            max_height: 900,
            every_nth_frame: 1,
            delivery_queue_size: 2,
          },
        }));
      };
      socket.onmessage = (message) => {
        if (message.data instanceof ArrayBuffer) {
          void drawFrame(message.data);
          return;
        }
        if (typeof message.data !== "string") return;
        const payload = JSON.parse(message.data) as Record<string, unknown>;
        if (payload.type === "monitor_ready") {
          applySnapshot(payload.snapshot as MonitorSnapshot);
          setConnectionState("live");
          if (typeof payload.visual_error === "string" && payload.visual_error) {
            setLastError(payload.visual_error);
          }
          return;
        }
        if (payload.type === "session_event") {
          const event = payload.event as SessionEvent;
          lastSequenceRef.current = Math.max(lastSequenceRef.current, event.sequence);
          setEvents((current) => [event, ...current].slice(0, MAX_EVENTS));
          return;
        }
        if (payload.type === "state_snapshot") {
          applySnapshot(payload.snapshot as MonitorSnapshot);
          return;
        }
        if (payload.type === "protocol_error") {
          setLastError(String(payload.message || "Monitor 协议错误"));
        }
      };
      socket.onerror = () => {
        setConnectionState("error");
        setLastError("无法连接 WebFA MonitorGateway");
      };
      socket.onclose = () => {
        socketRef.current = null;
        if (stoppedRef.current) return;
        setConnectionState("disconnected");
        reconnectTimerRef.current = window.setTimeout(() => void connect(), 1500);
      };
    } catch (error) {
      setConnectionState("error");
      setLastError(error instanceof Error ? error.message : String(error));
      reconnectTimerRef.current = window.setTimeout(() => void connect(), 2000);
    }
  }, [applySnapshot, drawFrame]);

  useEffect(() => {
    stoppedRef.current = false;
    void connect();
    return () => {
      stoppedRef.current = true;
      socketRef.current?.close();
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [connect]);

  const gridTemplateColumns = `${leftCollapsed ? "0px" : "270px"} minmax(0, 1fr) ${rightCollapsed ? "0px" : "340px"}`;
  const latestSafetyEvent = events.find((event) => event.event_type === "safety_decision_changed");
  const statusLabel = connectionState === "live" ? "实时连接" : connectionState === "connecting" ? "正在连接" : connectionState === "error" ? "连接错误" : "连接已断开";
  const activity = useMemo(() => events.filter((event) => event.event_type !== "frame_available"), [events]);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.logo}>W</div>
          <div>
            <div className={styles.brandTitle}>WebFA 会话监控</div>
            <div className={styles.brandMeta}>{snapshot?.active_agent_id || "等待 Agent"} · {snapshot?.session_id || "default"}</div>
          </div>
        </div>
        <div className={styles.headerActions}>
          <span className={`${styles.pill} ${connectionState === "live" ? styles.pillLive : ""}`}>{statusLabel}</span>
          <span className={styles.pill}>只读投影</span>
          <button className={styles.button} type="button" onClick={() => void window.webfaMonitor?.openControlCenter()}>控制中心</button>
        </div>
      </header>

      <section className={styles.workspace} style={{ gridTemplateColumns }}>
        <aside className={`${styles.sidebar} ${styles.left}`} aria-hidden={leftCollapsed}>
          <div className={styles.sidebarHeader}>
            <span className={styles.sidebarTitle}>会话上下文</span>
            <button className={styles.collapseButton} type="button" onClick={() => setLeftCollapsed(true)} aria-label="收起左栏">‹</button>
          </div>
          <div className={styles.cards}>
            <InfoCard title="Agent">
              <InfoRow label="当前 Agent" value={snapshot?.active_agent_id || "未连接"} />
              <InfoRow label="Session" value={snapshot?.session_id || "default"} />
              <InfoRow label="Profile" value={snapshot?.profile_id || "default"} />
            </InfoCard>
            <InfoCard title="当前页面">
              <InfoRow label="标题" value={snapshot?.title || "等待页面"} />
              <InfoRow label="页面" value={safeDisplayUrl(snapshot?.url)} />
              <InfoRow label="标签页" value={snapshot?.tab_id || "—"} />
              <InfoRow label="文档" value={shortId(snapshot?.document_id)} />
              <InfoRow label="对象数" value={String(snapshot?.object_count ?? 0)} />
            </InfoCard>
            <InfoCard title="Runtime 事实">
              <InfoRow label="文档修订" value={String(snapshot?.document_revision ?? 0)} />
              <InfoRow label="视觉帧" value={String(frameCount)} />
              <InfoRow label="接管要求" value={snapshot?.takeover_required ? snapshot.takeover_reason || "需要用户" : "无"} />
            </InfoCard>
          </div>
        </aside>

        <section className={styles.surfaceColumn}>
          <div className={styles.surfaceHeader}>
            <span className={styles.surfaceHeaderTitle}>页面表面</span>
            <span className={styles.surfaceHeaderMeta}>{safeDisplayUrl(snapshot?.url)}</span>
          </div>
          <div className={styles.surface}>
            <span className={styles.readonlyBadge}>WebFA BrowserHost 实时投影 · 不可操作</span>
            <div className={styles.canvasFrame} style={{ visibility: frameHeader ? "visible" : "hidden" }}>
              <canvas ref={canvasRef} className={styles.canvas} aria-label="WebFA BrowserHost visual surface" />
            </div>
            {!frameHeader && (
              <div className={styles.emptySurface}>
                正在等待 BrowserHost 视觉帧<br />
                Monitor 不会加载目标 URL，也不会创建第二个页面。
              </div>
            )}
          </div>
          <div className={styles.surfaceFooter}>
            <span>{frameHeader ? `${frameHeader.width} × ${frameHeader.height} · ${frameHeader.format.toUpperCase()}` : "暂无视觉帧"}</span>
            <span>{frameHeader ? `frame ${frameHeader.frame_seq} · ${shortId(frameHeader.document_id)}` : "只读监控模式"}</span>
          </div>
        </section>

        <aside className={`${styles.sidebar} ${styles.right}`} aria-hidden={rightCollapsed}>
          <div className={styles.sidebarHeader}>
            <span className={styles.sidebarTitle}>活动与安全</span>
            <button className={styles.collapseButton} type="button" onClick={() => setRightCollapsed(true)} aria-label="收起右栏">›</button>
          </div>
          <div className={styles.cards}>
            {lastError && <div className={`${styles.card} ${styles.error}`}><div className={styles.cardTitle}>连接信息</div>{lastError}</div>}
            <InfoCard title="当前安全状态">
              <InfoRow label="决策" value={String(latestSafetyEvent?.data.decision || "无待处理事项")} />
              <InfoRow label="状态" value={String(latestSafetyEvent?.data.status || "正常")} />
              <InfoRow label="用户处理" value={latestSafetyEvent?.data.requires_user_attention ? "需要" : "不需要"} />
            </InfoCard>
            <div className={styles.card}>
              <div className={styles.cardTitle}>实时活动</div>
              {activity.length === 0 ? <div className={styles.eventMeta}>等待 Runtime 事件</div> : activity.map((event) => (
                <div className={styles.event} key={event.event_id}>
                  <span className={`${styles.eventDot} ${event.data.requires_user_attention ? styles.eventAttention : ""}`} />
                  <div>
                    <div className={styles.eventTitle}>{eventLabel(event)}</div>
                    <div className={styles.eventMeta}>{new Date(event.timestamp).toLocaleTimeString()} · seq {event.sequence}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </section>

      {leftCollapsed && <button className={styles.restoreLeft} type="button" onClick={() => setLeftCollapsed(false)} aria-label="展开左栏">›</button>}
      {rightCollapsed && <button className={styles.restoreRight} type="button" onClick={() => setRightCollapsed(false)} aria-label="展开右栏">‹</button>}
    </main>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className={styles.card}><div className={styles.cardTitle}>{title}</div>{children}</div>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className={styles.row}><span className={styles.rowLabel}>{label}</span><span className={styles.rowValue}>{value}</span></div>;
}

function shortId(value?: string | null): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function safeDisplayUrl(value?: string | null): string {
  if (!value || value === "about:blank") return "等待页面";
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "file:") return `file://${parsed.pathname.split("/").pop() || "local"}`;
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return value.split("?")[0].split("#")[0];
  }
}

function eventLabel(event: SessionEvent): string {
  const labels: Record<string, string> = {
    session_started: "Session 已启动",
    session_closed: "Session 已关闭",
    navigation_started: "开始导航",
    navigation_committed: "页面导航完成",
    navigation_failed: "页面导航失败",
    document_changed: "页面状态已变化",
    tab_switched: "已切换标签页",
    operation_started: "Agent 开始执行操作",
    operation_completed: "Agent 操作已完成",
    operation_failed: "Agent 操作失败",
    safety_decision_changed: "安全状态已更新",
    takeover_required: "需要用户接管",
    visual_stream_started: "视觉流已启动",
    visual_stream_stopped: "视觉流已停止",
    browser_crashed: "BrowserHost 已退出",
  };
  const base = labels[event.event_type] || event.event_type;
  const operation = typeof event.data.operation === "string" ? ` · ${event.data.operation}` : "";
  return `${base}${operation}`;
}
