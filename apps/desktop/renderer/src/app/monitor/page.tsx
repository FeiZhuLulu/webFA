"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
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
const COMPACT_MONITOR_QUERY = "(max-width: 820px)";
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const HUMAN_CONTROL_REASON_LABELS: Record<string, string> = {
  authentication: "身份验证",
  manual_identity_confirmation: "身份确认",
  opaque_surface: "不透明页面",
};

function humanControlReasonLabel(reason: string | null | undefined) {
  if (!reason) return "人工接管";
  return HUMAN_CONTROL_REASON_LABELS[reason] || reason.replaceAll("_", " ");
}

export default function MonitorPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<MonitorSnapshot | null>(null);
  const lastSequenceRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const keyboardCaptureButtonRef = useRef<HTMLButtonElement | null>(null);
  const takeoverButtonRef = useRef<HTMLButtonElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const surfaceColumnRef = useRef<HTMLElement | null>(null);
  const leftSidebarRef = useRef<HTMLElement | null>(null);
  const rightSidebarRef = useRef<HTMLElement | null>(null);
  const leftRestoreRef = useRef<HTMLButtonElement | null>(null);
  const rightRestoreRef = useRef<HTMLButtonElement | null>(null);
  const desktopSidebarStateRef = useRef({ leftCollapsed: false, rightCollapsed: false });
  const wasCompactLayoutRef = useRef(false);
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
  const [waitingForSession, setWaitingForSession] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [compactLayout, setCompactLayout] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [humanControl, setHumanControl] = useState<HumanControlState>({
    active: false,
    leaseId: null,
    reason: null,
    expiresAt: null,
  });

  useEffect(() => {
    const media = window.matchMedia(COMPACT_MONITOR_QUERY);
    const syncLayout = () => {
      const nextCompactLayout = media.matches;
      setCompactLayout(nextCompactLayout);
      if (nextCompactLayout && !wasCompactLayoutRef.current) {
        setLeftCollapsed(true);
        setRightCollapsed(true);
      } else if (!nextCompactLayout && wasCompactLayoutRef.current) {
        setLeftCollapsed(desktopSidebarStateRef.current.leftCollapsed);
        setRightCollapsed(desktopSidebarStateRef.current.rightCollapsed);
      }
      wasCompactLayoutRef.current = nextCompactLayout;
    };
    syncLayout();
    media.addEventListener("change", syncLayout);
    return () => media.removeEventListener("change", syncLayout);
  }, []);

  const compactDrawerOpen = compactLayout && (!leftCollapsed || !rightCollapsed);
  useEffect(() => {
    headerRef.current?.toggleAttribute("inert", compactDrawerOpen);
    surfaceColumnRef.current?.toggleAttribute("inert", compactDrawerOpen);
    return () => {
      headerRef.current?.removeAttribute("inert");
      surfaceColumnRef.current?.removeAttribute("inert");
    };
  }, [compactDrawerOpen]);

  useEffect(() => {
    if (!humanControl.active) return;
    inputRef.current?.focus({ preventScroll: true });
  }, [humanControl.active]);

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

  const focusHumanControlKeyboard = useCallback(() => {
    inputRef.current?.focus({ preventScroll: true });
  }, []);

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
    if (event.key === "Escape" && !event.nativeEvent.isComposing && !compositionRef.current) {
      event.preventDefault();
      event.stopPropagation();
      keyboardCaptureButtonRef.current?.focus({ preventScroll: true });
      return;
    }
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
      if (config.status === "unavailable") {
        setWaitingForSession(false);
        setConnectionState(config.reason === "runtime_unavailable" ? "disconnected" : "error");
        setLastError(config.reason === "monitor_config_failed" ? "Monitor 配置暂不可用" : null);
        reconnectTimerRef.current = window.setTimeout(
          () => void connect(),
          config.retryAfterMs,
        );
        return;
      }
      if (config.status === "waiting") {
        setWaitingForSession(true);
        setConnectionState("disconnected");
        reconnectTimerRef.current = window.setTimeout(
          () => void connect(),
          config.retryAfterMs,
        );
        return;
      }
      setWaitingForSession(false);
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
          const keyboardCaptureHadFocus = !active && document.activeElement === inputRef.current;
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
          if (!active && keyboardCaptureHadFocus) {
            window.setTimeout(() => takeoverButtonRef.current?.focus({ preventScroll: true }), 0);
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
        const keyboardCaptureHadFocus = document.activeElement === inputRef.current;
        socketRef.current = null;
        frameDecodeGenerationRef.current += 1;
        snapshotRef.current = null;
        setSnapshot(null);
        setFrameHeader(null);
        setFrameCount(0);
        const canvas = canvasRef.current;
        const context = canvas?.getContext("2d");
        if (canvas && context) context.clearRect(0, 0, canvas.width, canvas.height);
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
        if (keyboardCaptureHadFocus) {
          window.setTimeout(() => takeoverButtonRef.current?.focus({ preventScroll: true }), 0);
        }
        if (stoppedRef.current) return;
        setConnectionState("disconnected");
        reconnectTimerRef.current = window.setTimeout(() => void connect(), 1500);
      };
    } catch (error) {
      setWaitingForSession(false);
      setConnectionState("error");
      setLastError(formatMonitorError(error));
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

  const humanLeaseExpiry = humanControl.expiresAt || snapshot?.human_control_expires_at || null;

  useEffect(() => {
    if (!snapshot?.agent_lease_expires_at && !humanLeaseExpiry) return;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [humanLeaseExpiry, snapshot?.agent_lease_expires_at]);

  const latestSafetyEvent = events.find((event) => event.event_type === "safety_decision_changed");
  const statusLabel = waitingForSession
    ? "等待会话"
    : connectionState === "live"
      ? "实时连接"
      : connectionState === "connecting"
        ? "正在连接"
        : connectionState === "error"
          ? "连接错误"
          : "连接已断开";
  const activity = useMemo(() => events.filter((event) => event.event_type !== "frame_available"), [events]);
  const workspaceClassName = [
    styles.workspace,
    leftCollapsed ? styles.workspaceLeftCollapsed : "",
    rightCollapsed ? styles.workspaceRightCollapsed : "",
  ].filter(Boolean).join(" ");
  const connectionClassName = waitingForSession
    ? styles.statusWaiting
    : connectionState === "live"
    ? styles.statusLive
    : connectionState === "connecting"
      ? styles.statusConnecting
      : styles.statusError;
  const agentLeaseLabel = formatLeaseRemaining(snapshot?.agent_lease_expires_at, nowMs);
  const humanLeaseLabel = formatLeaseRemaining(humanLeaseExpiry, nowMs);
  const emptyTitle = waitingForSession
    ? "等待外部 Agent 建立会话"
    : connectionState === "live" && lastError
      ? "视觉流暂不可用"
      : connectionState === "connecting"
        ? "正在建立安全监控通道"
        : connectionState === "error"
          ? "Monitor 连接失败"
          : connectionState === "disconnected"
            ? "Monitor 已断开"
            : "等待 BrowserHost 视觉帧";
  const emptyCopy = waitingForSession
    ? "外部 Agent 打开网页后，Monitor 会自动连接到活动 Browser Session。"
    : lastError || (connectionState === "connecting"
      ? "连接成功后会在这里投影同一个 BrowserHost 页面。"
      : connectionState === "disconnected"
        ? "正在等待 Runtime 恢复；连接可用后会自动重试。"
        : "Monitor 不加载目标 URL，也不会创建第二个页面。");

  const openSidebar = (panel: "left" | "right") => {
    if (panel === "left") {
      if (compactLayout) setRightCollapsed(true);
      setLeftCollapsed(false);
      if (!compactLayout) desktopSidebarStateRef.current.leftCollapsed = false;
      window.setTimeout(() => leftSidebarRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus(), 0);
    } else {
      if (compactLayout) setLeftCollapsed(true);
      setRightCollapsed(false);
      if (!compactLayout) desktopSidebarStateRef.current.rightCollapsed = false;
      window.setTimeout(() => rightSidebarRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus(), 0);
    }
  };

  const closeSidebar = (panel: "left" | "right", restoreFocus = true) => {
    if (panel === "left") {
      setLeftCollapsed(true);
      if (!compactLayout) desktopSidebarStateRef.current.leftCollapsed = true;
    } else {
      setRightCollapsed(true);
      if (!compactLayout) desktopSidebarStateRef.current.rightCollapsed = true;
    }
    if (compactLayout && restoreFocus) {
      const restore = panel === "left" ? leftRestoreRef : rightRestoreRef;
      window.setTimeout(() => restore.current?.focus(), 0);
    }
  };

  const handleDrawerKeyDown = (
    panel: "left" | "right",
    event: ReactKeyboardEvent<HTMLElement>,
  ) => {
    if (!compactLayout) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeSidebar(panel);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      .filter((element) => element.getClientRects().length > 0);
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#webfa-monitor-surface">跳至页面表面</a>
      <header className={styles.header} ref={headerRef}>
        <div className={styles.brand}>
          <div className={styles.logo} aria-hidden="true"><span /><span /></div>
          <div>
            <h1 className={styles.brandTitle}>WebFA 会话监控</h1>
            <div className={styles.brandMeta}>{snapshot?.active_agent_id || "等待外部 Agent"} · {snapshot?.session_id || "default"}</div>
          </div>
        </div>
        <div className={styles.headerActions} aria-live="polite">
          <span className={`${styles.statusChip} ${connectionClassName}`}>
            <span className={styles.statusDot} aria-hidden="true" />
            {statusLabel}
          </span>
          <span className={`${styles.statusChip} ${humanControl.active ? styles.statusHuman : styles.statusAgent}`}>
            {humanControl.active ? `用户控制${humanLeaseLabel ? ` · ${humanLeaseLabel}` : ""}` : "外部 Agent 控制"}
          </span>
          {humanControl.active && (
            <button
              ref={keyboardCaptureButtonRef}
              className={`${styles.button} ${styles.buttonKeyboard}`}
              type="button"
              onClick={focusHumanControlKeyboard}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                focusHumanControlKeyboard();
              }}
              aria-label="继续页面键盘控制"
              title="进入目标页面键盘输入；按 Esc 返回 Monitor 控件"
            >
              页面键盘
            </button>
          )}
          <button
            ref={takeoverButtonRef}
            className={`${styles.button} ${styles.buttonPrimary} ${humanControl.active ? styles.buttonRelease : snapshot?.takeover_required ? styles.buttonAttention : ""}`}
            type="button"
            disabled={connectionState !== "live" || (humanControl.active ? !humanControl.leaseId : !frameHeader)}
            onClick={humanControl.active ? releaseHumanControl : acquireHumanControl}
          >
            {humanControl.active ? "完成并归还 Agent" : snapshot?.takeover_required ? "开始人工接管" : "临时接管"}
          </button>
          <button className={styles.button} type="button" onClick={() => void window.webfaMonitor?.openControlCenter()}>控制中心</button>
        </div>
      </header>

      <section className={workspaceClassName} aria-label="Session Monitor 工作区">
        <aside
          ref={leftSidebarRef}
          className={`${styles.sidebar} ${styles.left}`}
          aria-label="会话上下文"
          aria-modal={compactLayout ? true : undefined}
          role={compactLayout ? "dialog" : undefined}
          hidden={leftCollapsed}
          onKeyDown={(event) => handleDrawerKeyDown("left", event)}
        >
          <div className={styles.sidebarHeader}>
            <h2 className={styles.sidebarTitle}>会话上下文</h2>
            <button className={styles.collapseButton} type="button" onClick={() => closeSidebar("left")} aria-label="收起左栏">‹</button>
          </div>
          <div className={styles.cards}>
            <InfoCard title="外部 Agent">
              <InfoRow label="连接身份" value={snapshot?.active_agent_id || "未连接"} />
              <InfoRow label="外部 Agent Lease" value={agentLeaseLabel || "未生效"} />
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
              <InfoRow label="接管要求" value={snapshot?.takeover_required ? humanControlReasonLabel(snapshot.takeover_reason) : "无"} />
              <InfoRow label="控制权" value={humanControl.active ? "当前用户" : "外部 Agent"} />
              <InfoRow label="接管 Lease" value={humanControl.active ? humanLeaseLabel || "有效" : "未生效"} />
            </InfoCard>
          </div>
        </aside>

        {compactDrawerOpen && (
          <button
            className={styles.drawerBackdrop}
            type="button"
            aria-label="关闭侧栏"
            onPointerDown={() => {
              if (!leftCollapsed) closeSidebar("left");
              if (!rightCollapsed) closeSidebar("right");
            }}
          />
        )}

        <section
          id="webfa-monitor-surface"
          ref={surfaceColumnRef}
          className={styles.surfaceColumn}
          tabIndex={-1}
        >
          <div className={styles.surfaceHeader}>
            <div className={styles.surfaceHeaderSide}>
              {leftCollapsed && <button ref={leftRestoreRef} className={styles.restoreButton} type="button" onClick={() => openSidebar("left")} aria-label="展开左栏">›</button>}
              <h2 className={styles.surfaceHeaderTitle}>页面表面</h2>
            </div>
            <div className={styles.surfaceHeaderSide}>
              <span className={styles.surfaceHeaderMeta}>{safeDisplayUrl(snapshot?.url)}</span>
              {rightCollapsed && <button ref={rightRestoreRef} className={styles.restoreButton} type="button" onClick={() => openSidebar("right")} aria-label="展开右栏">‹</button>}
            </div>
          </div>
          <div className={styles.surface} data-ui="monitor-surface">
            <span className={`${styles.readonlyBadge} ${humanControl.active ? styles.controlBadge : ""}`}>
              {humanControl.active
                ? `HumanControlLease · 用户正在控制同一页面${humanLeaseLabel ? ` · ${humanLeaseLabel}` : ""}`
                : waitingForSession
                  ? "等待活动 Browser Session · 只读监控"
                  : connectionState === "live"
                    ? "WebFA BrowserHost 实时投影 · 不可操作"
                    : connectionState === "connecting"
                      ? "正在建立 Monitor 连接 · 无实时页面"
                      : "Monitor 连接已断开 · 无实时页面"}
            </span>
            <div className={`${styles.canvasFrame} ${humanControl.active ? styles.canvasFrameActive : ""} ${!frameHeader ? styles.canvasFrameEmpty : ""}`}>
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
                  aria-describedby="webfa-human-control-keyboard-hint"
                  aria-keyshortcuts="Escape"
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
              <div
                className={`${styles.emptySurface} ${lastError ? styles.emptySurfaceError : ""}`}
                role={lastError ? "alert" : "status"}
                data-ui="monitor-empty-surface"
              >
                <div className={styles.emptyMark} aria-hidden="true"><span /><span /><span /></div>
                <div className={styles.emptyEyebrow}>{lastError || connectionState === "disconnected" ? "CONNECTION" : "LIVE SURFACE"}</div>
                <div className={styles.emptyTitle}>{emptyTitle}</div>
                <div className={styles.emptyCopy}>{emptyCopy}</div>
              </div>
            )}
          </div>
          <div className={styles.surfaceFooter}>
            <span>{frameHeader ? `${frameHeader.width} × ${frameHeader.height} · ${frameHeader.format.toUpperCase()}` : "暂无视觉帧"}</span>
            <span id="webfa-human-control-keyboard-hint">{humanControl.active ? `用户控制 · ${humanControlReasonLabel(humanControl.reason)} · Esc 返回 Monitor` : frameHeader ? `frame ${frameHeader.frame_seq} · ${shortId(frameHeader.document_id)}` : "只读监控模式"}</span>
          </div>
        </section>

        <aside
          ref={rightSidebarRef}
          className={`${styles.sidebar} ${styles.right}`}
          aria-label="活动与安全"
          aria-modal={compactLayout ? true : undefined}
          role={compactLayout ? "dialog" : undefined}
          hidden={rightCollapsed}
          onKeyDown={(event) => handleDrawerKeyDown("right", event)}
        >
          <div className={styles.sidebarHeader}>
            <h2 className={styles.sidebarTitle}>活动与安全</h2>
            <button className={styles.collapseButton} type="button" onClick={() => closeSidebar("right")} aria-label="收起右栏">›</button>
          </div>
          <div className={styles.cards}>
            {lastError && <div className={`${styles.card} ${styles.error}`} role="alert"><div className={styles.cardTitle}>连接信息</div><div className={styles.errorCopy}>{lastError}</div></div>}
            <InfoCard title="当前安全状态">
              <InfoRow label="决策" value={String(latestSafetyEvent?.data.decision || "无待处理事项")} />
              <InfoRow label="状态" value={String(latestSafetyEvent?.data.status || "正常")} />
              <InfoRow label="用户处理" value={latestSafetyEvent?.data.requires_user_attention ? "需要" : "不需要"} />
            </InfoCard>
            <div className={styles.card}>
              <div className={styles.cardTitle}>实时活动</div>
              {activity.length === 0 ? <div className={styles.activityEmpty}><span aria-hidden="true" />Runtime 事件会按发生顺序显示在这里</div> : activity.map((event) => (
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

    </main>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className={styles.card}><h3 className={styles.cardTitle}>{title}</h3>{children}</section>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className={styles.row}><span className={styles.rowLabel}>{label}</span><span className={styles.rowValue}>{value}</span></div>;
}

function formatMonitorError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/^Error invoking remote method 'monitor:getConfig': Error:\s*/i, "")
    .replace(/^Failed to issue Monitor grant \(\d+\):\s*/i, "");
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

function formatLeaseRemaining(value: string | null | undefined, nowMs: number): string {
  if (!value) return "";
  const expiresAt = Date.parse(value);
  if (!Number.isFinite(expiresAt)) return "到期时间未知";
  const seconds = Math.max(0, Math.ceil((expiresAt - nowMs) / 1000));
  if (seconds <= 0) return "已到期";
  if (seconds < 60) return `${seconds}秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}分${remainder}秒` : `${minutes}分钟`;
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
    operation_started: "外部 Agent 开始执行操作",
    operation_completed: "外部 Agent 操作已完成",
    operation_failed: "外部 Agent 操作失败",
    safety_decision_changed: "安全状态已更新",
    takeover_required: "需要用户接管",
    takeover_started: "用户已接管页面",
    takeover_finished: "页面已归还外部 Agent",
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
