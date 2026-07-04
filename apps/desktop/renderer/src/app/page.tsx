"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { VisualizerShell } from "../components/Layout/VisualizerShell";
import { ActionLogger } from "../components/Inspector/ActionLogger";
import { AgentStateInspector } from "../components/Inspector/AgentStateInspector";
import { ContentBlocksList } from "../components/Inspector/ContentBlocksList";
import { ElementTable } from "../components/Inspector/ElementTable";
import { PagePreview } from "../components/Preview/PagePreview";
import { ControlPanel } from "../components/Runtime/ControlPanel";
import { StatusPanel } from "../components/Runtime/StatusPanel";
import { closeAuthSurface, fetchVisualizerState, openAuthSurface, resolveApiUrl, restartHost } from "../lib/visualizer-api";
import type { VisualizerState } from "../types/visualizer";
import type { RuntimeState } from "../types/webfa-desktop";

const POLL_MS = 2500;

function mapDesktopRuntimeState(state: RuntimeState): "running" | "stopped" | "error" {
  if (state === "running") return "running";
  if (state === "error") return "error";
  return "stopped";
}

export default function VisualizerPage() {
  const [apiUrl, setApiUrl] = useState(resolveApiUrl());
  const apiUrlRef = useRef(apiUrl);
  const [runtimeState, setRuntimeState] = useState<"running" | "stopped" | "error">("stopped");
  const [visualizerState, setVisualizerState] = useState<VisualizerState | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [jsonExpanded, setJsonExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const browserState = visualizerState?.browser_state ?? null;
  const authSurfaceActive = Boolean(visualizerState?.auth_surface?.active);
  const authSurfaceUrl = visualizerState?.auth_surface?.url ?? visualizerState?.page.url ?? null;
  const hasElectronAuthSurface = typeof window !== "undefined" && Boolean(window.webfaDesktop?.showAuthSurface);

  useEffect(() => {
    apiUrlRef.current = apiUrl;
  }, [apiUrl]);

  const refresh = useCallback(async (preferredApiUrl?: string) => {
    const targetApiUrl = resolveApiUrl(preferredApiUrl || apiUrlRef.current);
    try {
      const health = await fetch(`${targetApiUrl}/health`, { cache: "no-store" });
      if (!health.ok) throw new Error(`Health failed: ${health.status}`);
      const healthJson = (await health.json()) as { api?: { url?: string } };
      const resolved = resolveApiUrl(healthJson.api?.url || targetApiUrl);
      apiUrlRef.current = resolved;
      setApiUrl(resolved);
      setRuntimeState("running");
      const next = await fetchVisualizerState(resolved);
      setVisualizerState(next);
      setLastError(null);
    } catch (error) {
      setRuntimeState((current) => (current === "running" ? "error" : "stopped"));
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  const runControl = useCallback(async (action: () => Promise<VisualizerState>) => {
    setBusy(true);
    try {
      const next = await action();
      setVisualizerState(next);
      setRuntimeState("running");
      setLastError(null);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, []);

  const copyJson = useCallback(async () => {
    if (!browserState) {
      setToast("尚无 BrowserState 可复制");
      return;
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(browserState, null, 2));
      setToast("BrowserState JSON 已复制");
    } catch {
      setToast("复制失败");
    }
  }, [browserState]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const config = await window.webfaDesktop?.getDesktopConfig();
        if (!cancelled && config?.apiUrl) {
          apiUrlRef.current = config.apiUrl;
          setApiUrl(config.apiUrl);
        }
      } catch {
        // browser-only mode
      }

      const status = await window.webfaDesktop?.getRuntimeStatus();
      if (!cancelled && status) {
        setRuntimeState(mapDesktopRuntimeState(status.state));
      }

      if (!cancelled) {
        await refresh(apiUrlRef.current);
      }
    }

    void bootstrap();
    const id = window.setInterval(() => void refresh(), POLL_MS);
    const unsubscribe = window.webfaDesktop?.onRuntimeStatus((status) => {
      setRuntimeState(mapDesktopRuntimeState(status.state));
      if (status.state === "running") {
        void refresh(status.apiUrl);
      }
    });

    return () => {
      cancelled = true;
      window.clearInterval(id);
      unsubscribe?.();
    };
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(id);
  }, [toast]);

  useEffect(() => {
    if (!hasElectronAuthSurface || !visualizerState) {
      return;
    }
    if (visualizerState.page.auth.user_action_required && !authSurfaceActive) {
      void runControl(() => openAuthSurface(apiUrlRef.current, visualizerState.page.url || null));
    }
  }, [hasElectronAuthSurface, visualizerState?.page.auth.user_action_required, authSurfaceActive, runControl, visualizerState]);

  const completeAuth = useCallback(async () => {
    const surfaceStatus = await window.webfaDesktop?.destroyAuthSurface();
    await runControl(() => closeAuthSurface(apiUrlRef.current, surfaceStatus?.url ?? authSurfaceUrl));
  }, [authSurfaceUrl, runControl]);

  const header = useMemo(
    () => (
      <header className="viz-app-header">
        <div className="viz-brand">
          <span className="viz-brand-name">WebFA Visualizer</span>
          <span className="viz-tag-version">P9 MVP</span>
        </div>
        <div className="viz-header-status">
          <span className={`viz-header-pill ${runtimeState}`}>{runtimeState}</span>
          {visualizerState?.agent.active_agent_id && (
            <span className="viz-header-pill agent">agent: {visualizerState.agent.active_agent_id}</span>
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
            <div className="viz-column-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <span className="viz-column-title">Runtime</span>
              <button type="button" className="viz-sidebar-toggle-arrow" onClick={() => setLeftCollapsed(true)} title="收起左侧">
                <svg className="viz-icon" viewBox="0 0 24 24" width="14" height="14">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            </div>
            <StatusPanel state={visualizerState} runtimeState={runtimeState} apiUrl={apiUrl} />
            <div className="viz-column-header">
              <span className="viz-column-title">Controls</span>
            </div>
            <ControlPanel
              busy={busy}
              hostActionsDisabled={runtimeState !== "running"}
              onRefresh={() => runControl(() => fetchVisualizerState(apiUrlRef.current))}
              onRestartHost={() => runControl(() => restartHost(apiUrlRef.current))}
              onOpenAuthSurface={() => runControl(() => openAuthSurface(apiUrlRef.current, visualizerState?.page.url || null))}
              onCopyJson={() => void copyJson()}
              onStartRuntime={async () => {
                const status = await window.webfaDesktop?.startRuntime();
                if (status) {
                  setRuntimeState(mapDesktopRuntimeState(status.state));
                  if (status.apiUrl) {
                    apiUrlRef.current = status.apiUrl;
                    setApiUrl(status.apiUrl);
                  }
                  if (status.state === "running") {
                    await refresh(status.apiUrl);
                  }
                }
              }}
              onStopRuntime={async () => {
                const status = await window.webfaDesktop?.stopRuntime();
                if (status) {
                  setRuntimeState(mapDesktopRuntimeState(status.state));
                }
              }}
            />
          </>
        }
        main={
          <PagePreview
            state={visualizerState}
            authSurfaceActive={authSurfaceActive && hasElectronAuthSurface}
            authSurfaceUrl={authSurfaceUrl}
            onCompleteAuth={hasElectronAuthSurface ? () => void completeAuth() : undefined}
          />
        }
        right={
          <>
            <div className="viz-panel-section">
              <div className="viz-column-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                <span className="viz-column-title">Agent View</span>
                <button type="button" className="viz-sidebar-toggle-arrow" onClick={() => setRightCollapsed(true)} title="收起右侧">
                  <svg className="viz-icon" viewBox="0 0 24 24" width="14" height="14">
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

      {(lastError || toast) && (
        <div className="viz-toast-stack">
          {lastError && <div className="viz-toast error">{lastError}</div>}
          {toast && <div className="viz-toast ok">{toast}</div>}
        </div>
      )}
    </>
  );
}
