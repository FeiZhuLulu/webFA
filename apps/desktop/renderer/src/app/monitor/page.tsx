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
  human_control_active: boolean;
  human_control_reason: string | null;
  human_control_expires_at: string | null;
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

type HumanControlState = {
  active: boolean;
  leaseId: string | null;
  reason: string | null;
  expiresAt: string | null;
};

const MAX_EVENTS = 80;

export default function MonitorPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<MonitorSnapshot | null>(null);
  const lastSequenceRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const compositionRef = useRef(false);
  const skipNextBeforeInputRef = useRef(false);
  const compositionSkipTimerRef = useRef<number | null>(null);
  const pendingMoveRef = useRef<{ x: number; y: number; buttons: number } | null>(null);
  const activePointerRef = useRef<{
    x: number;
    y: number;
    button: "none" | "left" | "middle" | "right" | "back" | "forward";
  } | null>(null);
  const moveFrameRef = useRef<number | null>(null);
  const frameDecodeGenerationRef = useRef(0);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [frameHeader, setFrameHeader] = useState<VisualFrameHeader | null>(null);
  const [frameCount, setFrameCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [humanControl, setHumanControl] = useState<HumanControlState>({
    active: false,
    leaseId: null,
    reason: null,
    expiresAt: null,
  });

  const applySnapshot = useCallback((nextSnapshot: MonitorSnapshot) => {
    const previous = snapshotRef.current;
    if (
      previous &&
      (previous.session_id !== nextSnapshot.session_id ||
        previous.tab_id !== nextSnapshot.tab_id ||
        previous.document_id !== nextSnapshot.document_id)
    ) {
      frameDecodeGenerationRef.current += 1;
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
      const decodeGeneration = ++frameDecodeGenerationRef.current;
      const imageBytes = packet.slice(headerEnd);
      const mime = header.format === "jpeg" ? "image/jpeg" : `image/${header.format}`;
      const bitmap = await createImageBitmap(new Blob([imageBytes], { type: mime }));
      if (decodeGeneration !== frameDecodeGenerationRef.current) {
        bitmap.close();
        return;
      }
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

  const sendMonitorMessage = useCallback((payload: Record<string, unknown>): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }, []);

  const acquireHumanControl = useCallback(() => {
    if (!sendMonitorMessage({
      type: "human_control_acquire",
      reason: snapshotRef.current?.takeover_reason || "manual_identity_confirmation",
      ttl_seconds: 300,
    })) {
      setLastError("MonitorGateway 尚未连接");
    }
  }, [sendMonitorMessage]);

  const releaseHumanControl = useCallback(() => {
    if (!humanControl.leaseId) return;
    if (moveFrameRef.current !== null) {
      window.cancelAnimationFrame(moveFrameRef.current);
      moveFrameRef.current = null;
    }
    pendingMoveRef.current = null;
    const activePointer = activePointerRef.current;
    if (activePointer) {
      sendMonitorMessage({
        type: "human_input",
        lease_id: humanControl.leaseId,
        event: {
          type: "mouse_up",
          x: activePointer.x,
          y: activePointer.y,
          button: activePointer.button,
          buttons: 0,
          click_count: 1,
        },
      });
      activePointerRef.current = null;
    }
    sendMonitorMessage({
      type: "human_control_release",
      lease_id: humanControl.leaseId,
    });
  }, [humanControl.leaseId, sendMonitorMessage]);

  const sendHumanInput = useCallback((event: Record<string, unknown>) => {
    if (!humanControl.active || !humanControl.leaseId) return;
    sendMonitorMessage({
      type: "human_input",
      lease_id: humanControl.leaseId,
      event,
    });
  }, [humanControl.active, humanControl.leaseId, sendMonitorMessage]);

  const surfacePoint = useCallback((event: { clientX: number; clientY: number }) => {
    const canvas = canvasRef.current;
    const header = frameHeader;
    if (!canvas || !header) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: Math.max(0, Math.min(header.width, ((event.clientX - rect.left) / rect.width) * header.width)),
      y: Math.max(0, Math.min(header.height, ((event.clientY - rect.top) / rect.height) * header.height)),
    };
  }, [frameHeader]);

  const onSurfacePointerMove = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!humanControl.active) return;
    const point = surfacePoint(event);
    if (!point) return;
    pendingMoveRef.current = { ...point, buttons: event.buttons };
    if (activePointerRef.current) {
      activePointerRef.current = {
        ...activePointerRef.current,
        x: point.x,
        y: point.y,
      };
    }
    if (moveFrameRef.current !== null) return;
    moveFrameRef.current = window.requestAnimationFrame(() => {
      moveFrameRef.current = null;
      const pending = pendingMoveRef.current;
      pendingMoveRef.current = null;
      if (!pending) return;
      sendHumanInput({
        type: "mouse_move",
        x: pending.x,
        y: pending.y,
        button: "none",
        buttons: pending.buttons,
      });
    });
  }, [humanControl.active, sendHumanInput, surfacePoint]);

  const onSurfacePointerButton = useCallback((event: React.PointerEvent<HTMLCanvasElement>, type: "mouse_down" | "mouse_up") => {
    if (!humanControl.active) return;
    event.preventDefault();
    if (type === "mouse_down") {
      event.currentTarget.setPointerCapture(event.pointerId);
      inputRef.current?.focus({ preventScroll: true });
    } else if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const point = surfacePoint(event);
    if (!point) return;
    const button = mouseButtonName(event.button);
    if (type === "mouse_down") {
      activePointerRef.current = { ...point, button };
    }
    sendHumanInput({
      type,
      x: point.x,
      y: point.y,
      button,
      buttons: event.buttons,
      click_count: event.detail > 1 ? Math.min(event.detail, 3) : 1,
      modifiers: eventModifiers(event),
    });
    if (type === "mouse_up") activePointerRef.current = null;
  }, [humanControl.active, sendHumanInput, surfacePoint]);

  const onSurfacePointerCancel = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!humanControl.active) return;
    const point = surfacePoint(event);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const activePointer = activePointerRef.current;
    activePointerRef.current = null;
    if (!point && !activePointer) return;
    sendHumanInput({
      type: "mouse_up",
      x: point?.x ?? activePointer?.x ?? 0,
      y: point?.y ?? activePointer?.y ?? 0,
      button: activePointer?.button ?? mouseButtonName(event.button),
      buttons: 0,
      click_count: 1,
      modifiers: eventModifiers(event),
    });
  }, [humanControl.active, sendHumanInput, surfacePoint]);

  const onSurfaceWheel = useCallback((event: React.WheelEvent<HTMLCanvasElement>) => {
    if (!humanControl.active) return;
    event.preventDefault();
    const point = surfacePoint(event);
    if (!point) return;
    sendHumanInput({
      type: "wheel",
      x: point.x,
      y: point.y,
      delta_x: event.deltaX,
      delta_y: event.deltaY,
      buttons: event.buttons,
      modifiers: eventModifiers(event),
    });
  }, [humanControl.active, sendHumanInput, surfacePoint]);

  const onInputKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!humanControl.active) return;
    const pasteShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v";
    if (pasteShortcut) return;
    const composing = event.nativeEvent.isComposing || compositionRef.current;
    const printable = event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (!printable && !composing) event.preventDefault();
    sendHumanInput({
      type: "key_down",
      key: event.key,
      code: event.code,
      modifiers: eventModifiers(event),
      auto_repeat: event.repeat,
    });
  }, [humanControl.active, sendHumanInput]);

  const onInputKeyUp = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!humanControl.active) return;
    const pasteShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v";
    if (pasteShortcut) return;
    if (!event.nativeEvent.isComposing) event.preventDefault();
    sendHumanInput({
      type: "key_up",
      key: event.key,
      code: event.code,
      modifiers: eventModifiers(event),
    });
  }, [humanControl.active, sendHumanInput]);

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
        if (payload.type === "human_control_state") {
          const active = payload.active === true;
          if (!active) {
            if (moveFrameRef.current !== null) {
              window.cancelAnimationFrame(moveFrameRef.current);
              moveFrameRef.current = null;
            }
            pendingMoveRef.current = null;
            activePointerRef.current = null;
            compositionRef.current = false;
            skipNextBeforeInputRef.current = false;
            if (compositionSkipTimerRef.current !== null) {
              window.clearTimeout(compositionSkipTimerRef.current);
              compositionSkipTimerRef.current = null;
            }
            if (inputRef.current) inputRef.current.value = "";
          }
          setHumanControl({
            active,
            leaseId: active && typeof payload.lease_id === "string" ? payload.lease_id : null,
            reason: active && typeof payload.reason === "string" ? payload.reason : null,
            expiresAt: active && typeof payload.expires_at === "string" ? payload.expires_at : null,
          });
          if (active) {
            window.setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 0);
          }
          return;
        }
        if (payload.type === "human_control_error") {
          setLastError(String(payload.message || "人工接管失败"));
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
        frameDecodeGenerationRef.current += 1;
        if (moveFrameRef.current !== null) {
          window.cancelAnimationFrame(moveFrameRef.current);
          moveFrameRef.current = null;
        }
        pendingMoveRef.current = null;
        activePointerRef.current = null;
        compositionRef.current = false;
        skipNextBeforeInputRef.current = false;
        if (compositionSkipTimerRef.current !== null) {
          window.clearTimeout(compositionSkipTimerRef.current);
          compositionSkipTimerRef.current = null;
        }
        if (inputRef.current) inputRef.current.value = "";
        setHumanControl({ active: false, leaseId: null, reason: null, expiresAt: null });
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
      if (moveFrameRef.current !== null) {
        window.cancelAnimationFrame(moveFrameRef.current);
      }
      if (compositionSkipTimerRef.current !== null) {
        window.clearTimeout(compositionSkipTimerRef.current);
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
          <span className={`${styles.pill} ${humanControl.active ? styles.pillHuman : ""}`}>
            {humanControl.active ? "用户控制中" : "Agent 控制"}
          </span>
          <button
            className={`${styles.button} ${humanControl.active ? styles.buttonRelease : snapshot?.takeover_required ? styles.buttonAttention : ""}`}
            type="button"
            disabled={connectionState !== "live" || !frameHeader}
            onClick={humanControl.active ? releaseHumanControl : acquireHumanControl}
          >
            {humanControl.active ? "完成并归还 Agent" : snapshot?.takeover_required ? "开始人工接管" : "临时接管"}
          </button>
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
              <InfoRow label="控制权" value={humanControl.active ? "当前用户" : "Agent"} />
            </InfoCard>
          </div>
        </aside>

        <section className={styles.surfaceColumn}>
          <div className={styles.surfaceHeader}>
            <span className={styles.surfaceHeaderTitle}>页面表面</span>
            <span className={styles.surfaceHeaderMeta}>{safeDisplayUrl(snapshot?.url)}</span>
          </div>
          <div className={styles.surface}>
            <span className={`${styles.readonlyBadge} ${humanControl.active ? styles.controlBadge : ""}`}>
              {humanControl.active
                ? "HumanControlLease · 用户正在控制同一 BrowserHost 页面"
                : "WebFA BrowserHost 实时投影 · 不可操作"}
            </span>
            <div className={`${styles.canvasFrame} ${humanControl.active ? styles.canvasFrameActive : ""}`} style={{ visibility: frameHeader ? "visible" : "hidden" }}>
              <canvas
                ref={canvasRef}
                className={`${styles.canvas} ${humanControl.active ? styles.canvasInteractive : ""}`}
                aria-label="WebFA BrowserHost visual surface"
                onPointerMove={onSurfacePointerMove}
                onPointerDown={(event) => onSurfacePointerButton(event, "mouse_down")}
                onPointerUp={(event) => onSurfacePointerButton(event, "mouse_up")}
                onPointerCancel={onSurfacePointerCancel}
                onWheel={onSurfaceWheel}
                onContextMenu={(event) => humanControl.active && event.preventDefault()}
              />
              {humanControl.active && (
                <textarea
                  ref={inputRef}
                  className={styles.inputCapture}
                  aria-label="人工接管键盘输入捕获"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  onKeyDown={onInputKeyDown}
                  onKeyUp={onInputKeyUp}
                  onCompositionStart={() => { compositionRef.current = true; }}
                  onCompositionEnd={(event) => {
                    compositionRef.current = false;
                    if (event.data) {
                      skipNextBeforeInputRef.current = true;
                      if (compositionSkipTimerRef.current !== null) {
                        window.clearTimeout(compositionSkipTimerRef.current);
                      }
                      compositionSkipTimerRef.current = window.setTimeout(() => {
                        skipNextBeforeInputRef.current = false;
                        compositionSkipTimerRef.current = null;
                      }, 0);
                      sendHumanInput({ type: "insert_text", text: event.data });
                    }
                    event.currentTarget.value = "";
                  }}
                  onBeforeInput={(event) => {
                    const native = event.nativeEvent as InputEvent;
                    if (skipNextBeforeInputRef.current) {
                      skipNextBeforeInputRef.current = false;
                      if (compositionSkipTimerRef.current !== null) {
                        window.clearTimeout(compositionSkipTimerRef.current);
                        compositionSkipTimerRef.current = null;
                      }
                      return;
                    }
                    if (!compositionRef.current && native.data) {
                      sendHumanInput({ type: "insert_text", text: native.data });
                    }
                  }}
                  onInput={(event) => { event.currentTarget.value = ""; }}
                  onPaste={(event) => {
                    event.preventDefault();
                    const text = event.clipboardData.getData("text");
                    if (text) sendHumanInput({ type: "insert_text", text });
                  }}
                />
              )}
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
            <span>{humanControl.active ? `用户控制 · ${humanControl.reason || "人工接管"}` : frameHeader ? `frame ${frameHeader.frame_seq} · ${shortId(frameHeader.document_id)}` : "只读监控模式"}</span>
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
    takeover_started: "用户已接管页面",
    takeover_finished: "页面已归还 Agent",
    visual_stream_started: "视觉流已启动",
    visual_stream_stopped: "视觉流已停止",
    browser_crashed: "BrowserHost 已退出",
  };
  const base = labels[event.event_type] || event.event_type;
  const operation = typeof event.data.operation === "string" ? ` · ${event.data.operation}` : "";
  return `${base}${operation}`;
}

function mouseButtonName(button: number): "none" | "left" | "middle" | "right" | "back" | "forward" {
  if (button === 0) return "left";
  if (button === 1) return "middle";
  if (button === 2) return "right";
  if (button === 3) return "back";
  if (button === 4) return "forward";
  return "none";
}

function eventModifiers(event: {
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}): string[] {
  const modifiers: string[] = [];
  if (event.altKey) modifiers.push("alt");
  if (event.ctrlKey) modifiers.push("control");
  if (event.metaKey) modifiers.push("meta");
  if (event.shiftKey) modifiers.push("shift");
  return modifiers;
}
