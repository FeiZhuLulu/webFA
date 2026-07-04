from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_electron_runtime_manager_starts_uvicorn_runtime():
    source = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    assert "apps.runtime.main:app" in source
    assert "uvicorn" in source
    assert "spawn" in source
    assert "WEBFA_PYTHON" in source


def test_electron_auth_surface_ipc_exists():
    main = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    preload = (ROOT / "apps/desktop/electron/preload.ts").read_text(encoding="utf-8")
    auth_surface = (ROOT / "apps/desktop/electron/authSurface.ts").read_text(encoding="utf-8")
    assert "auth-surface:show" in main
    assert "WebContentsView" in auth_surface
    assert "showAuthSurface" in preload
    assert "devTools: false" in auth_surface
    assert "contextIsolation: true" in auth_surface
    assert 'action: "deny"' in auth_surface
    assert "WEBFA_HOME" in auth_surface
    assert "managed-chromium-profile-default" in auth_surface
    assert "authSurfaceManager.destroy()" in main


def test_electron_exposes_runtime_start_stop_ipc():
    source = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert 'ipcMain.handle("runtime:start"' in source
    assert 'ipcMain.handle("runtime:stop"' in source
    assert "before-quit" in source
    assert "runtimeManager.stop()" in source


def test_renderer_has_stopped_state_for_runtime_stop():
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    api = (ROOT / "apps/desktop/renderer/src/lib/visualizer-api.ts").read_text(encoding="utf-8")
    assert '"stopped"' in page
    assert "stopRuntime" in page
    assert "fetchVisualizerState" in page
    assert "/v1/visualizer/state" in api
    assert "open-auth-surface" in api


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
