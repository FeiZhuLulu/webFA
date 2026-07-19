"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { VisualizerShell } from "../components/Layout/VisualizerShell";
import { ActionLogger } from "../components/Inspector/ActionLogger";
import { AgentStateInspector } from "../components/Inspector/AgentStateInspector";
import { ContentBlocksList } from "../components/Inspector/ContentBlocksList";
import { ElementTable } from "../components/Inspector/ElementTable";
import { PagePreview, type RuntimeSurfaceNotice } from "../components/Preview/PagePreview";
import { ControlPanel } from "../components/Runtime/ControlPanel";
import { McpStatusPanel } from "../components/Runtime/McpStatusPanel";
import { ProfileBootstrapPanel } from "../components/Runtime/ProfileBootstrapPanel";
import { ResourceGrantPanel } from "../components/Runtime/ResourceGrantPanel";
import { SafetyCenterPanel } from "../components/Runtime/SafetyCenterPanel";
import { StatusPanel } from "../components/Runtime/StatusPanel";
import {
  fetchVisualizerState,
  resolveApiUrl,
  restartHost,
  setVisualizerControlToken,
} from "../lib/visualizer-api";
import { presentRuntimeIssue } from "../lib/runtime-presentation";
import type { VisualizerState } from "../types/visualizer";
import type { RuntimeState, RuntimeStatus } from "../types/webfa-desktop";

const POLL_MS = 2500;
type ControlSection = "overview" | "identity" | "safety";
type RuntimeConnectionState = "checking" | "ready" | "unreachable" | "idle";

function mapDesktopRuntimeState(state: RuntimeState): RuntimeState {
  return state;
}

function formatUiError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/failed to fetch|fetch failed|networkerror/i.test(message)) {
    return "无法连接本地 WebFA Runtime";
  }
  const healthFailure = message.match(/^Health failed: (\d+)$/);
  if (healthFailure) return `Runtime 健康检查失败（HTTP ${healthFailure[1]}）`;
  if (message === "Runtime identity mismatch") return "连接的本地服务不是 WebFA Runtime";
  return message;
}

export default function VisualizerPage() {
  const [apiUrl, setApiUrl] = useState(resolveApiUrl());
  const apiUrlRef = useRef(apiUrl);
  const [runtimeState, setRuntimeState] = useState<RuntimeState>("starting");
  const [connectionState, setConnectionState] = useState<RuntimeConnectionState>("checking");
  const [desktopRuntimeStatus, setDesktopRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const desktopRuntimeStatusRef = useRef<RuntimeStatus | null>(null);
  const [visualizerState, setVisualizerState] = useState<VisualizerState | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [controlSection, setControlSection] = useState<ControlSection>("overview");
  const [jsonExpanded, setJsonExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const handleUiError = useCallback((error: string) => {
    setLastError(formatUiError(error));
  }, []);

  const browserState = visualizerState?.browser_state ?? null;

  useEffect(() => {
    apiUrlRef.current = apiUrl;
  }, [apiUrl]);

  const syncDesktopConfig = useCallback(async () => {
    const config = await window.webfaDesktop?.getDesktopConfig();
    if (!config?.apiUrl) return config;
    setVisualizerControlToken(config.visualizerControlToken);
    apiUrlRef.current = config.apiUrl;
    setApiUrl(config.apiUrl);
    return config;
  }, []);

  const refresh = useCallback(async (preferredApiUrl?: string) => {
    const targetApiUrl = resolveApiUrl(preferredApiUrl || apiUrlRef.current);
    try {
      const health = await fetch(`${targetApiUrl}/health`, { cache: "no-store" });
      if (!health.ok) throw new Error(`Health failed: ${health.status}`);
      const healthJson = (await health.json()) as { product?: string };
      if (healthJson.product !== "webfa") throw new Error("Runtime identity mismatch");
      apiUrlRef.current = targetApiUrl;
      setApiUrl(targetApiUrl);
      if (!window.webfaDesktop) setRuntimeState("running");
      const next = await fetchVisualizerState(targetApiUrl);
      setVisualizerState(next);
      setConnectionState("ready");
      setLastError(null);
    } catch (error) {
      if (!window.webfaDesktop) {
        setRuntimeState((current) => (current === "running" ? "error" : "stopped"));
      }
      setVisualizerState(null);
      setConnectionState("unreachable");
      setLastError(formatUiError(error));
    }
  }, []);

  const runControl = useCallback(async (action: () => Promise<VisualizerState>) => {
    setBusy(true);
    try {
      const next = await action();
      setVisualizerState(next);
      setRuntimeState("running");
      setConnectionState("ready");
      setLastError(null);
    } catch (error) {
      setLastError(formatUiError(error));
    } finally {
      setBusy(false);
    }
  }, []);

  const copyJson = useCallback(async () => {
    const stateToCopy = visualizerState?.web_state ?? browserState;
    if (!stateToCopy) {
      setToast("尚无 Runtime 页面投影可复制");
      return;
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(stateToCopy, null, 2));
      setToast(`${visualizerState?.web_state ? "WebState" : "BrowserState"} JSON 已复制`);
    } catch {
      setToast("复制失败");
    }
  }, [browserState, visualizerState?.web_state]);

  const applyDesktopStatus = useCallback((status: RuntimeStatus) => {
    desktopRuntimeStatusRef.current = status;
    setDesktopRuntimeStatus(status);
    setRuntimeState(mapDesktopRuntimeState(status.state));
    setLastError(status.lastError ?? null);
    if (status.state === "running") {
      setConnectionState((current) => current === "idle" ? "checking" : current);
    } else {
      setConnectionState("idle");
      setVisualizerControlToken(null);
      setVisualizerState(null);
    }
  }, []);

  const startDesktopRuntime = useCallback(async () => {
    const desktop = window.webfaDesktop;
    if (!desktop) return;
    setBusy(true);
    setLastError(null);
    setConnectionState("checking");
    try {
      const status = await desktop.startRuntime();
      applyDesktopStatus(status);
      if (status.apiUrl) {
        apiUrlRef.current = status.apiUrl;
        setApiUrl(status.apiUrl);
      }
      if (status.state === "running") await refresh(status.apiUrl);
    } catch (error) {
      setConnectionState("unreachable");
      setLastError(formatUiError(error));
    } finally {
      setBusy(false);
    }
  }, [applyDesktopStatus, refresh]);

  const stopDesktopRuntime = useCallback(async () => {
    const desktop = window.webfaDesktop;
    if (!desktop) return;
    setBusy(true);
    try {
      const status = await desktop.stopRuntime();
      applyDesktopStatus(status);
    } catch (error) {
      setLastError(formatUiError(error));
    } finally {
      setBusy(false);
    }
  }, [applyDesktopStatus]);

  useEffect(() => {
    let cancelled = false;
    let pollInFlight = false;
    const desktop = window.webfaDesktop;

    async function synchronize() {
      if (cancelled || pollInFlight) return;
      pollInFlight = true;
      try {
        const status = await desktop?.getRuntimeStatus();
        if (cancelled) return;
        if (status) applyDesktopStatus(status);
        if (!desktop || status?.state === "running") {
          await syncDesktopConfig();
          if (cancelled) return;
          await refresh(status?.apiUrl ?? apiUrlRef.current);
        }
      } catch (error) {
        if (!cancelled && desktop) setLastError(formatUiError(error));
      } finally {
        pollInFlight = false;
      }
    }

    void synchronize();
    const id = window.setInterval(() => void synchronize(), POLL_MS);
    const unsubscribe = desktop?.onRuntimeStatus((status) => {
      applyDesktopStatus(status);
      if (status.state === "running") {
        void (async () => {
          await syncDesktopConfig();
          await refresh(status.apiUrl);
        })();
      }
    });

    return () => {
      cancelled = true;
      window.clearInterval(id);
      unsubscribe?.();
    };
  }, [applyDesktopStatus, refresh, syncDesktopConfig]);

  const previousConnectionState = useRef<RuntimeConnectionState>(connectionState);
  useEffect(() => {
    const previous = previousConnectionState.current;
    previousConnectionState.current = connectionState;
    if (previous === "unreachable" && connectionState === "ready") {
      setToast("Runtime 已恢复连接");
    }
  }, [connectionState]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(id);
  }, [toast]);

  const runtimeNotice = useMemo<RuntimeSurfaceNotice | null>(() => {
    const issue = presentRuntimeIssue(desktopRuntimeStatus);
    const retryStart = () => void startDesktopRuntime();
    const retryConnection = () => {
      setConnectionState("checking");
      void refresh(apiUrlRef.current);
    };

    if (runtimeState === "starting") {
      return {
        tone: "progress",
        eyebrow: "DESKTOP RUNTIME",
        title: "正在启动 WebFA Runtime",
        detail: "Desktop 正在验证进程、版本、实例身份与本地控制权。验证完成前不会向界面或外部 Agent 发放控制令牌。",
        statusLabel: "启动中",
        meta: apiUrl,
      };
    }

    if (runtimeState === "error") {
      const cleanupPending = desktopRuntimeStatus?.issue?.recovery === "retry_stop";
      return {
        tone: issue?.tone ?? "error",
        eyebrow: issue?.eyebrow ?? "RUNTIME",
        title: issue?.title ?? "Runtime 当前不可用",
        detail: issue?.detail ?? "Desktop 已停止展示旧状态。请检查本地应用日志后重试。",
        statusLabel: "需要处理",
        meta: apiUrl,
        actionLabel: issue?.actionLabel ?? "重试启动",
        actionDisabled: busy,
        onAction: cleanupPending ? () => void stopDesktopRuntime() : retryStart,
      };
    }

    if (runtimeState === "stopped") {
      return {
        tone: "neutral",
        eyebrow: "DESKTOP RUNTIME",
        title: "Runtime 已停止",
        detail: "Profile 数据仍保留在 WebFA 应用目录中；当前没有 Runtime、BrowserHost 或控制令牌处于活动状态。",
        statusLabel: "已停止",
        meta: apiUrl,
        actionLabel: "启动 Runtime",
        actionDisabled: busy,
        onAction: retryStart,
      };
    }

    if (connectionState === "checking") {
      return {
        tone: "progress",
        eyebrow: "LOCAL CONNECTION",
        title: "正在连接 Runtime",
        detail: "进程身份已经建立，控制中心正在取得受保护的状态投影。这里不会继续展示上一轮连接留下的数据。",
        statusLabel: "连接中",
        meta: apiUrl,
      };
    }

    if (connectionState === "unreachable") {
      return {
        tone: "warning",
        eyebrow: "LOCAL CONNECTION",
        title: "Runtime 暂时不可达",
        detail: "控制中心已清除旧状态并保持最小权限。后台会继续检测；也可以立即重新检查本地连接。",
        statusLabel: "连接中断",
        meta: apiUrl,
        actionLabel: "立即重新检查",
        actionDisabled: busy,
        onAction: retryConnection,
      };
    }

    if (visualizerState?.runtime.executable_found === false) {
      return {
        tone: "warning",
        eyebrow: "BROWSER PREREQUISITE",
        title: "浏览器运行环境未就绪",
        detail: "Runtime 已在线，但没有发现受支持的 Chrome 或 Edge，因此外部 Agent 还不能打开网页。安装浏览器后可直接重新检测。",
        statusLabel: "缺少浏览器",
        meta: apiUrl,
        actionLabel: "重新检测浏览器",
        actionDisabled: busy,
        onAction: retryConnection,
      };
    }

    return null;
  }, [
    apiUrl,
    busy,
    connectionState,
    desktopRuntimeStatus,
    refresh,
    runtimeState,
    startDesktopRuntime,
    stopDesktopRuntime,
    visualizerState?.runtime.executable_found,
  ]);

  const header = useMemo(
    () => (
      <header className="viz-app-header">
        <div className="viz-brand">
          <span className="viz-brand-mark" aria-hidden="true">
            <span />
            <span />
          </span>
          <span className="viz-brand-copy">
            <span className="viz-brand-name">WebFA</span>
            <span className="viz-brand-subtitle">Runtime manager</span>
          </span>
        </div>
        <div className="viz-header-status">
          {typeof window !== "undefined" && window.webfaDesktop?.openMonitor && (
            <button
              type="button"
              className="viz-btn viz-btn-primary"
              disabled={runtimeState !== "running"}
              onClick={() => void window.webfaDesktop?.openMonitor()}
              title={runtimeState === "running" ? undefined : "Runtime 就绪后可打开会话监控"}
            >
              打开会话监控
            </button>
          )}
          <span className={`viz-header-pill ${runtimeState}`} aria-label={`Runtime 状态：${runtimeState}`}>
            <span className="viz-header-status-dot" aria-hidden="true" />
            {runtimeState}
          </span>
          {visualizerState?.agent.active_agent_id && (
            <span className="viz-header-pill agent">agent · {visualizerState.agent.active_agent_id}</span>
          )}
        </div>
      </header>
    ),
    [runtimeState, visualizerState?.agent.active_agent_id],
  );

  return (
    <>
      <VisualizerShell
        header={header}
        leftCollapsed={leftCollapsed}
        rightCollapsed={rightCollapsed}
        onToggleLeft={() => setLeftCollapsed((value) => !value)}
        onToggleRight={() => setRightCollapsed((value) => !value)}
        left={
          <>
            <div className="viz-column-header viz-sidebar-heading">
              <span>
                <span className="viz-column-eyebrow">Operations</span>
                <span className="viz-column-heading">控制面板</span>
              </span>
              <button
                type="button"
                className="viz-sidebar-toggle-arrow"
                data-webfa-panel-collapse="left"
                onClick={() => setLeftCollapsed(true)}
                aria-label="收起控制面板"
              >
                <svg className="viz-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            </div>
            <nav className="viz-sidebar-nav" aria-label="控制面板分区">
              {([
                ["overview", "概览"],
                ["identity", "身份"],
                ["safety", "安全"],
              ] as const).map(([section, label]) => (
                <button
                  key={section}
                  type="button"
                  className={`viz-sidebar-nav-item${controlSection === section ? " active" : ""}`}
                  aria-pressed={controlSection === section}
                  onClick={() => setControlSection(section)}
                >
                  {label}
                </button>
              ))}
            </nav>
            <div className="viz-sidebar-scroll">
              {controlSection === "overview" && <section className="viz-sidebar-pane">
                <div className="viz-column-header">
                  <span className="viz-column-title">Runtime status</span>
                </div>
                <StatusPanel
                  state={visualizerState}
                  runtimeState={runtimeState}
                  desktopStatus={desktopRuntimeStatus}
                  apiUrl={apiUrl}
                />
                <div className="viz-column-header">
                  <span className="viz-column-title">外部 Agent 接入</span>
                </div>
                <McpStatusPanel
                  apiUrl={apiUrl}
                  runtimeState={runtimeState}
                  activeAgentId={visualizerState?.agent.active_agent_id ?? null}
                  leaseExpiresAt={visualizerState?.agent.lease_expires_at ?? null}
                />
                <div className="viz-column-header">
                  <span className="viz-column-title">Runtime controls</span>
                </div>
                <ControlPanel
                  busy={busy}
                  hostActionsDisabled={runtimeState !== "running"}
                  onRefresh={() => runControl(() => fetchVisualizerState(apiUrlRef.current))}
                  onRestartHost={() => runControl(() => restartHost(apiUrlRef.current))}
                  onOpenMonitor={() => void window.webfaDesktop?.openMonitor()}
                  onCopyJson={() => void copyJson()}
                  startDisabled={
                    runtimeState === "starting" ||
                    (desktopRuntimeStatus?.ownership === "desktop" && Boolean(desktopRuntimeStatus.pid))
                  }
                  stopDisabled={!desktopRuntimeStatus?.pid}
                  onStartRuntime={startDesktopRuntime}
                  onStopRuntime={stopDesktopRuntime}
                />
              </section>}
              {controlSection === "identity" && <section className="viz-sidebar-pane">
                <div className="viz-column-header">
                  <span className="viz-column-title">Profile bootstrap</span>
                </div>
                <ProfileBootstrapPanel
                  apiUrl={apiUrl}
                  currentProfileId={visualizerState?.profile.profile_id ?? "default"}
                  disabled={runtimeState !== "running"}
                  onChanged={() => refresh(apiUrlRef.current)}
                  onMessage={setToast}
                  onError={handleUiError}
                />
              </section>}
              {controlSection === "safety" && <section className="viz-sidebar-pane">
                <div className="viz-column-header">
                  <span className="viz-column-title">Local resource grants</span>
                </div>
                <ResourceGrantPanel
                  apiUrl={apiUrl}
                  resources={visualizerState?.local_resources ?? []}
                  pageUrl={visualizerState?.page.url ?? ""}
                  activeAgentId={visualizerState?.agent.active_agent_id ?? null}
                  profileId={visualizerState?.profile.profile_id ?? "default"}
                  disabled={runtimeState !== "running"}
                  onChanged={() => refresh(apiUrlRef.current)}
                  onMessage={setToast}
                  onError={handleUiError}
                />
                <div className="viz-column-header">
                  <span className="viz-column-title">Safety center</span>
                </div>
                <SafetyCenterPanel
                  apiUrl={apiUrl}
                  profile={visualizerState?.profile ?? {
                    profile_id: "default",
                    shared: true,
                    owner: "shared",
                    trust_mode: "trusted_agent",
                    unknown_external_effect_policy: "require_step_up",
                    bound_agent_ids: [],
                    allowed_origins: [],
                    safety_policy_id: null,
                    financial_policy_id: null,
                  }}
                  activeAgentId={visualizerState?.agent.active_agent_id ?? null}
                  pageUrl={visualizerState?.page.url ?? ""}
                  financialPolicies={visualizerState?.financial_policies ?? []}
                  paymentInstruments={visualizerState?.payment_instruments ?? []}
                  stepUps={visualizerState?.step_ups ?? []}
                  receipts={visualizerState?.safety_receipts ?? []}
                  disabled={runtimeState !== "running"}
                  onChanged={() => refresh(apiUrlRef.current)}
                  onMessage={setToast}
                  onError={handleUiError}
                />
              </section>}
            </div>
          </>
        }
        main={
          <PagePreview
            state={visualizerState}
            runtimeNotice={runtimeNotice}
            monitorDisabled={runtimeState !== "running"}
            onOpenMonitor={() => void window.webfaDesktop?.openMonitor()}
          />
        }
        right={
          <>
            <div className="viz-panel-section">
              <div className="viz-column-header viz-right-heading">
                <span className="viz-column-title">Runtime Projection</span>
                <button
                  type="button"
                  className="viz-sidebar-toggle-arrow"
                  data-webfa-panel-collapse="right"
                  onClick={() => setRightCollapsed(true)}
                  aria-label="收起 Runtime 投影"
                >
                  <svg className="viz-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>
              </div>
              <div className="viz-column-content compact">
                <ElementTable elements={browserState?.interactive_elements ?? []} focusedId={browserState?.focused_element_id ?? null} />
              </div>
            </div>
            <div className="viz-panel-section blocks">
              <div className="viz-column-header">
                <span className="viz-column-title">Content Blocks</span>
              </div>
              <div className="viz-column-content compact">
                <ContentBlocksList blocks={browserState?.content_blocks ?? []} />
              </div>
            </div>
            <div className="viz-panel-section console">
              <div className="viz-column-header">
                <span className="viz-column-title">Action Log</span>
              </div>
              <ActionLogger entries={visualizerState?.recent_actions ?? []} />
            </div>
            <div className="viz-panel-section json">
              <AgentStateInspector browserState={browserState} expanded={jsonExpanded} onToggle={() => setJsonExpanded((value) => !value)} />
            </div>
          </>
        }
      />

      {((lastError && !runtimeNotice) || toast) && (
        <div className="viz-toast-stack" aria-live="polite">
          {lastError && !runtimeNotice && <div className="viz-toast error" role="alert">{lastError}</div>}
          {toast && <div className="viz-toast ok" role="status">{toast}</div>}
        </div>
      )}
    </>
  );
}
