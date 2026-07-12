from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_electron_runtime_manager_starts_uvicorn_runtime():
    source = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    assert "apps.runtime.main:app" in source
    assert "uvicorn" in source
    assert "spawn" in source
    assert "WEBFA_PYTHON" in source


def test_electron_duplicate_page_auth_surface_is_not_exposed():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/preload.ts").read_text(encoding="utf-8")
    page_preview = (ROOT / "apps/desktop/renderer/src/components/Preview/PagePreview.tsx").read_text(encoding="utf-8")
    deprecated_viewport = (ROOT / "apps/desktop/renderer/src/components/Preview/AuthSurfaceViewport.tsx").read_text(encoding="utf-8")
    retired_surface = (ROOT / "apps/desktop/electron/authSurface.ts").read_text(encoding="utf-8")

    assert "AuthSurfaceManager" not in main
    assert "auth-surface:show" not in main
    assert "showAuthSurface" not in preload
    assert "destroyAuthSurface" not in preload
    assert "WebContentsView" not in page_preview
    assert "loadURL" not in page_preview
    assert 'from "electron"' not in retired_surface
    assert "new WebContentsView" not in retired_surface
    assert ".loadURL(" not in retired_surface
    assert "HumanControlLease" in retired_surface
    assert "HumanControlLease" in deprecated_viewport


def test_electron_exposes_runtime_start_stop_ipc():
    source = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert 'ipcMain.handle("runtime:start"' in source
    assert 'ipcMain.handle("runtime:stop"' in source
    assert "before-quit" in source
    assert "runtimeManager.stop()" in source


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
    assert "NEXT_PUBLIC_WEBFA_VISUALIZER_CONTROL_TOKEN" not in renderer_api


def test_electron_monitor_uses_separate_scoped_preload_and_same_page_canvas():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/monitorPreload.ts").read_text(encoding="utf-8")
    page = (ROOT / "apps/desktop/renderer/src/app/monitor/page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "apps/desktop/renderer/src/app/monitor/monitor.module.css").read_text(encoding="utf-8")

    assert 'ipcMain.handle("monitor:getConfig"' in main
    assert "monitorPreload.js" in main
    assert "/v1/visualizer/monitor-grants" in main
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
    assert 'permissions: ["events", "frames", "takeover"]' in main


def test_renderer_has_stopped_state_for_runtime_stop():
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    api = (ROOT / "apps/desktop/renderer/src/lib/visualizer-api.ts").read_text(encoding="utf-8")
    assert '"stopped"' in page
    assert "stopRuntime" in page
    assert "fetchVisualizerState" in page
    assert "/v1/visualizer/state" in api
    assert "openMonitor" in page


def test_electron_mcp_process_manager_exists():
    source = (ROOT / "apps/desktop/electron/mcpProcess.ts").read_text(encoding="utf-8")
    assert "apps.runtime.mcp.server" in source
    assert "spawn" in source
    assert "WEBFA_RUNTIME_URL" in source
    assert "start" in source
    assert "stop" in source
    assert "restart" in source


def test_electron_exposes_mcp_ipc():
    source = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert 'ipcMain.handle("mcp:start"' in source
    assert 'ipcMain.handle("mcp:stop"' in source
    assert 'ipcMain.handle("mcp:restart"' in source
    assert 'ipcMain.handle("mcp:getStatus"' in source
    assert "mcpManager.stop()" in source


def test_electron_preload_exposes_mcp():
    source = (ROOT / "apps/desktop/electron/preload.ts").read_text(encoding="utf-8")
    assert "getMcpStatus" in source
    assert "startMcp" in source
    assert "stopMcp" in source
    assert "restartMcp" in source
    assert "onMcpStatus" in source


def test_electron_no_mcp_business_logic():
    source = (ROOT / "apps/desktop/electron/mcpProcess.ts").read_text(encoding="utf-8")
    assert "plan_hash" not in source
    assert "approval_token" not in source
    assert "policy" not in source.lower() or "policy" not in source
    assert "proof" not in source.lower() or "proof" not in source
