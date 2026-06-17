from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_electron_runtime_manager_starts_uvicorn_runtime():
    source = (ROOT / "apps/desktop/electron/runtimeProcess.ts").read_text(encoding="utf-8")
    assert "apps.runtime.main:app" in source
    assert "uvicorn" in source
    assert "spawn" in source
    assert "WEBFA_PYTHON" in source


def test_electron_exposes_runtime_start_stop_ipc():
    source = (ROOT / "apps/desktop/electron/main.ts").read_text(encoding="utf-8")
    assert 'ipcMain.handle("runtime:start"' in source
    assert 'ipcMain.handle("runtime:stop"' in source
    assert "before-quit" in source
    assert "runtimeManager.stop()" in source


def test_renderer_has_stopped_state_for_runtime_stop():
    source = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    assert 'state: "stopped"' in source
    assert "stopRuntime" in source or "Stop Runtime" in source
    assert "stopped" in source


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
