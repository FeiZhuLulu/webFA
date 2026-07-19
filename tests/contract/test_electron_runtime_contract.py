from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_electron_runtime_manager_starts_uvicorn_runtime():
    source = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    termination = (ROOT / "apps/desktop/electron/processTermination.ts").read_text(encoding="utf-8")
    assert "apps.runtime.main:app" in source
    assert "uvicorn" in source
    assert "spawn" in source
    assert "WEBFA_PYTHON" in source
    assert "if (this.child || this.startPromise || this.stopPromise)" in source
    assert "this.isCurrent(child)" in source
    assert "await this.terminateProcess(child)" in source
    assert "probeRuntimeEndpoint" in source
    assert "WEBFA_RUNTIME_INSTANCE_ID" in source
    assert "canIssueControlToken" in source
    assert 'process.kill(-child.pid, signal)' in termination
    assert 'spawn(resolveWindowsTaskkillPath()' in termination
    assert '"System32", "taskkill.exe"' in termination


def test_electron_runtime_manager_has_a_source_free_sidecar_mode():
    source = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")

    assert "sidecarExecutable" in source
    assert '["runtime", "--host", this.host, "--port", String(this.port)]' in source
    assert "delete inheritedEnv.PYTHONPATH" in source
    assert "WEBFA_MCP_COMMAND" in source
    assert "WEBFA_MCP_ARGS_JSON" in source
    assert "WEBFA_HOME: this.dataDirectory" in source


def test_packaged_electron_uses_static_loopback_renderer_and_sidecar():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    renderer_server = (ROOT / "apps/desktop/electron/rendererServer.ts").read_text(encoding="utf-8")
    next_config = (ROOT / "apps/desktop/renderer/next.config.js").read_text(encoding="utf-8")

    assert "app.isPackaged" in main
    assert "RendererAssetServer" in main
    assert "process.resourcesPath" in main
    assert '"sidecar"' in main
    assert "WEBFA_SIDECAR_EXECUTABLE" not in main
    assert "rendererServer.stop()" in main
    assert 'dataDirectory: app.isPackaged ? app.getPath("userData")' in main
    assert "minWidth: 720" in main
    assert 'output: "export"' in next_config
    assert "trailingSlash: true" in next_config
    assert 'listen(0, LOOPBACK_HOST' in renderer_server
    assert "path.resolve(this.root, relativePath)" in renderer_server
    assert "isPathWithin(this.root, candidate)" in renderer_server
    assert "isPathWithin(this.realRoot, realCandidate)" in renderer_server
    assert "await fs.realpath(candidate)" in renderer_server
    assert "integrityProtectedArchive" in renderer_server
    assert "body = await fs.readFile(candidate)" in renderer_server
    assert "integrityProtectedArchive: appArchive" in main
    assert "Content-Security-Policy" in renderer_server
    assert "file:" not in main


def test_electron_duplicate_page_auth_surface_is_not_exposed():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/preload.ts").read_text(encoding="utf-8")
    page_preview = (ROOT / "apps/desktop/renderer/src/components/Preview/PagePreview.tsx").read_text(encoding="utf-8")

    assert "AuthSurfaceManager" not in main
    assert "auth-surface:show" not in main
    assert "showAuthSurface" not in preload
    assert "destroyAuthSurface" not in preload
    assert "WebContentsView" not in page_preview
    assert "loadURL" not in page_preview
    assert not (ROOT / "apps/desktop/electron/authSurface.ts").exists()
    assert not (
        ROOT / "apps/desktop/renderer/src/components/Preview/AuthSurfaceViewport.tsx"
    ).exists()


def test_electron_exposes_runtime_start_stop_ipc():
    source = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert 'ipcMain.handle("runtime:start"' in source
    assert 'ipcMain.handle("runtime:stop"' in source
    assert "before-quit" in source
    assert "runtimeManager.stop()" in source
    assert "event.preventDefault()" in source
    assert "if (shutdownComplete) return" in source
    assert "if (shutdownStarted) return" in source
    assert "await runtimeManager.stop()" in source
    assert "shutdownComplete = true" in source
    assert "could not shut down safely" in source
    assert "shutdownStarted" in source
    assert "requestSingleInstanceLock" in source


def test_electron_visualizer_control_token_is_runtime_only_and_renderer_is_origin_locked():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    runtime_process = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    renderer_api = (ROOT / "apps/desktop/renderer/src/lib/visualizer-api.ts").read_text(encoding="utf-8")

    assert "randomBytes(32)" in main
    assert "requireTrustedMainRenderer" in main
    assert "event.sender.id !== mainWindow.webContents.id" in main
    assert 'webContents.on("will-navigate"' in main
    assert 'webContents.on("will-redirect"' in main
    assert "setWindowOpenHandler" in main
    assert main.count("sandbox: true") >= 2
    assert "sandbox: false" not in main
    assert "WEBFA_VISUALIZER_CONTROL_TOKEN" in runtime_process
    assert "buildPackagedRuntimeEnvironment" in runtime_process
    assert "WEBFA_STRICT_CONSOLE_ORIGINS" in runtime_process
    assert "runtimeManager.getControlToken()" in main
    assert "this.canIssueControlToken()" in runtime_process
    assert "requireOwnedRuntimeControl()" in main
    assert "NEXT_PUBLIC_WEBFA_VISUALIZER_CONTROL_TOKEN" not in renderer_api


def test_electron_monitor_uses_separate_scoped_preload_and_same_page_canvas():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/monitorPreload.ts").read_text(encoding="utf-8")
    page = (ROOT / "apps/desktop/renderer/src/app/monitor/page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/renderer/src/app/monitor/monitor.module.css").read_text(encoding="utf-8")

    assert 'ipcMain.handle("monitor:getConfig"' in main
    assert "monitorPreload.js" in main
    assert "/v1/visualizer/monitor-grants" in main
    assert "/v1/visualizer/sessions" in main
    assert "visualizerControlToken" not in preload
    assert "startRuntime" not in preload
    assert "approveStepUp" not in preload
    assert "new WebSocket" in page
    assert "createImageBitmap" in page
    assert "<canvas" in page
    assert "iframe" not in page.lower()
    assert "loadURL" not in page
    assert "pointer-events: none" in styles
    assert "human_control_acquire" in page
    assert "human_input" in page
    assert "HumanControlLease" in page
    assert 'status: "waiting"' in main
    assert 'reason: "no_active_session"' in main
    assert 'status: "unavailable"' in main
    assert 'reason: "runtime_unavailable" | "monitor_config_failed"' in main
    assert 'config.status === "unavailable"' in page
    assert 'config.status === "waiting"' in page
    assert "等待外部 Agent 建立会话" in page
    assert "formatMonitorError" in page
    assert "Monitor 连接失败" in page
    assert "Monitor 已断开" in page
    assert "Monitor 连接已断开 · 无实时页面" in page
    assert "snapshotRef.current = null" in page
    assert "setFrameHeader(null)" in page
    assert "setFrameCount(0)" in page
    assert 'context.clearRect(0, 0, canvas.width, canvas.height)' in page
    assert "WebFA 会话监控" in (ROOT / "apps/desktop/renderer/src/app/monitor/layout.tsx").read_text(encoding="utf-8")
    assert "hidden={leftCollapsed}" in page
    assert "hidden={rightCollapsed}" in page
    assert "gridTemplateColumns" not in page
    assert "agent_lease_expires_at" in page
    assert "humanLeaseLabel" in page
    assert "useEffect(() => {\n    if (!humanControl.active) return;\n    inputRef.current?.focus" in page
    assert 'event.key === "Escape"' in page
    assert "keyboardCaptureButtonRef.current?.focus" in page
    assert "takeoverButtonRef.current?.focus" in page
    assert "focusHumanControlKeyboard" in page
    assert 'event.key !== "Enter" && event.key !== " "' in page
    assert '(humanControl.active ? !humanControl.leaseId : !frameHeader)' in page
    assert "desktopSidebarStateRef" in page
    assert "wasCompactLayoutRef" in page
    assert "if (compactLayout) setRightCollapsed(true)" in page
    assert "if (compactLayout) setLeftCollapsed(true)" in page
    assert 'aria-label="继续页面键盘控制"' in page
    assert 'aria-keyshortcuts="Escape"' in page
    assert "Esc 返回 Monitor" in page
    assert ".buttonKeyboard" in styles
    assert 'const COMPACT_MONITOR_QUERY = "(max-width: 820px)"' in page
    assert 'aria-modal={compactLayout ? true : undefined}' in page
    assert 'surfaceColumnRef.current?.toggleAttribute("inert", compactDrawerOpen)' in page
    assert 'onKeyDown={(event) => handleDrawerKeyDown("left", event)}' in page
    assert 'onKeyDown={(event) => handleDrawerKeyDown("right", event)}' in page
    assert 'href="#webfa-monitor-surface"' in page
    assert "grid-column: 2" in styles
    assert "@media (max-width: 820px)" in styles
    assert ".drawerBackdrop" in styles
    assert "100dvh" in styles
    assert ":focus-visible" in styles
    assert "prefers-reduced-motion: reduce" in styles
    assert 'permissions: ["events", "frames", "takeover"]' in main


def test_control_center_reconciles_desktop_runtime_status_and_gates_monitor_entry():
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    preview = (ROOT / "apps/desktop/renderer/src/components/Preview/PagePreview.tsx").read_text(
        encoding="utf-8"
    )
    styles = (ROOT / "apps/desktop/renderer/src/app/globals.css").read_text(encoding="utf-8")

    assert "async function synchronize()" in page
    assert "await desktop?.getRuntimeStatus()" in page
    assert "window.setInterval(() => void synchronize(), POLL_MS)" in page
    assert 'disabled={runtimeState !== "running"}' in page
    assert 'monitorDisabled={runtimeState !== "running"}' in page
    assert "disabled={monitorDisabled}" in preview
    assert 'className="viz-preview-heading"' in preview
    assert ".viz-preview-heading" in styles
    assert "flex: 0 0 auto" in styles
    assert "white-space: nowrap" in styles
    assert "presentRuntimeIssue" in page
    assert "runtimeNotice={runtimeNotice}" in page
    assert 'setConnectionState("unreachable")' in page
    assert "setVisualizerState(null)" in page
    assert "Runtime 端口被其他服务占用" in (
        ROOT / "apps/desktop/renderer/src/lib/runtime-presentation.ts"
    ).read_text(encoding="utf-8")
    assert "viz-runtime-notice" in preview
    assert ".viz-runtime-notice" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_renderer_has_stopped_state_for_runtime_stop():
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    api = (ROOT / "apps/desktop/renderer/src/lib/visualizer-api.ts").read_text(encoding="utf-8")
    shell = (ROOT / "apps/desktop/renderer/src/components/Layout/VisualizerShell.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/renderer/src/app/globals.css").read_text(encoding="utf-8")
    status_panel = (ROOT / "apps/desktop/renderer/src/components/Runtime/StatusPanel.tsx").read_text(encoding="utf-8")
    assert '"stopped"' in page
    assert "stopRuntime" in page
    assert "fetchVisualizerState" in page
    assert "/v1/visualizer/state" in api
    assert "openMonitor" in page
    assert "hidden={leftHidden}" in shell
    assert "hidden={rightHidden}" in shell
    assert 'const COMPACT_LAYOUT_QUERY = "(max-width: 920px)"' in shell
    assert 'aria-modal={compactLayout && !leftHidden ? true : undefined}' in shell
    assert 'aria-modal={compactLayout && !rightHidden ? true : undefined}' in shell
    assert 'mainRef.current?.toggleAttribute("inert", backgroundIsInert)' in shell
    assert 'onPointerDown={() => closeCompactPanel()}' in shell
    assert 'data-webfa-panel-collapse="${panel}"' in shell
    assert 'data-webfa-panel-collapse="left"' in page
    assert 'data-webfa-panel-collapse="right"' in page
    assert "@media (max-width: 920px)" in styles
    assert ".viz-drawer-backdrop" in styles
    assert ".viz-column[hidden]" in styles
    assert "grid-column: 1" in styles
    assert "grid-column: 2" in styles
    assert "grid-column: 3" in styles
    assert "executable_found" in status_panel
    assert "需要安装 Chrome 或 Edge" in status_panel
    assert 'role="alert"' in status_panel


def test_desktop_runtime_failures_are_structured_and_bounded_before_renderer_ipc():
    runtime = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    renderer_types = (
        ROOT / "apps/desktop/renderer/src/types/webfa-desktop.d.ts"
    ).read_text(encoding="utf-8")

    for issue in (
        "external_runtime",
        "endpoint_collision",
        "ownership_changed",
        "spawn_failed",
        "startup_timeout",
        "startup_failed",
        "runtime_exited",
        "cleanup_failed",
    ):
        assert f'"{issue}"' in runtime
        assert f'"{issue}"' in renderer_types
    assert "issue?: RuntimeIssue" in runtime
    assert "issue?: RuntimeIssue" in renderer_types
    assert "lastError: text.trim()" not in runtime
    assert "console.error" in runtime


def test_electron_does_not_own_an_orphan_mcp_stdio_process():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/preload.ts").read_text(encoding="utf-8")

    assert "McpProcessManager" not in main
    assert 'ipcMain.handle("mcp:' not in main
    assert "mcpManager" not in main
    assert "Start MCP Server" not in main
    assert "getMcpStatus" not in preload
    assert "startMcp" not in preload
    assert "stopMcp" not in preload
    assert "restartMcp" not in preload
    assert not (ROOT / "apps/desktop/electron/mcpProcess.ts").exists()
