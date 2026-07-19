from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from apps.runtime import cli
from apps.runtime.version import __version__


def test_runtime_entrypoint_propagates_bound_address_to_runtime_state(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)

    exit_code = cli.main_runtime(["start", "--host", "127.0.0.2", "--port", "9123"])

    assert exit_code == 0
    assert captured == {
        "app": "apps.runtime.main:app",
        "host": "127.0.0.2",
        "port": 9123,
        "log_level": "info",
    }
    assert cli.os.environ["WEBFA_API_HOST"] == "127.0.0.2"
    assert cli.os.environ["WEBFA_API_PORT"] == "9123"


def test_webfa_multicall_dispatches_runtime_mode(monkeypatch):
    captured: dict[str, object] = {}

    def fake_runtime(command: str, host: str, port: int) -> int:
        captured.update(command=command, host=host, port=port)
        return 17

    monkeypatch.setattr(cli, "_run_runtime", fake_runtime)

    exit_code = cli.main_webfa(["runtime", "--host", "127.0.0.2", "--port", "9123"])

    assert exit_code == 17
    assert captured == {"command": "start", "host": "127.0.0.2", "port": 9123}


def test_webfa_multicall_dispatches_mcp_mode(monkeypatch):
    captured: dict[str, object] = {}

    def fake_mcp(runtime_url: str | None, *, no_auto_start: bool) -> int:
        captured.update(runtime_url=runtime_url, no_auto_start=no_auto_start)
        return 18

    monkeypatch.setattr(cli, "_run_mcp", fake_mcp)

    exit_code = cli.main_webfa(["mcp", "--runtime-url", "http://127.0.0.1:9123", "--no-auto-start"])

    assert exit_code == 18
    assert captured == {"runtime_url": "http://127.0.0.1:9123", "no_auto_start": True}


def test_pyproject_declares_console_scripts():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["webfa"] == "apps.runtime.cli:main_webfa"
    assert scripts["webfa-runtime"] == "apps.runtime.cli:main_runtime"
    assert scripts["webfa-mcp"] == "apps.runtime.cli:main_mcp"


def test_python_distribution_reads_version_from_the_runtime_version_module():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dynamic"] == ["version"]
    assert "version" not in pyproject["project"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "apps.runtime.version.__version__"
    }


def test_webfa_version_uses_the_canonical_runtime_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main_webfa(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"webfa {__version__}"


def test_webfa_mcp_config_prints_installed_command(capsys):
    exit_code = cli.main_webfa(["mcp-config", "--runtime-url", "http://127.0.0.1:8787"])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    entry = body["mcpServers"]["webfa"]
    assert entry["command"] == "webfa-mcp"
    assert entry["env"]["WEBFA_RUNTIME_URL"] == "http://127.0.0.1:8787"
    assert entry["env"]["WEBFA_AGENT_ID"] == "external-agent"


def test_webfa_mcp_config_prints_opencode_config(capsys):
    exit_code = cli.main_webfa([
        "mcp-config",
        "--runtime-url",
        "http://127.0.0.1:8787",
        "--client",
        "opencode",
        "--agent-id",
        "opencode",
    ])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    entry = body["mcp"]["webfa"]
    assert entry["command"] == ["webfa-mcp"]
    assert entry["environment"]["WEBFA_RUNTIME_URL"] == "http://127.0.0.1:8787"
    assert entry["environment"]["WEBFA_AGENT_ID"] == "opencode"


def test_webfa_status_reports_unreachable(monkeypatch, capsys):
    monkeypatch.setattr(cli, "runtime_health", lambda runtime_url: None)

    exit_code = cli.main_webfa(["status", "--runtime-url", "http://127.0.0.1:65500"])

    assert exit_code == 1
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "unreachable"


def test_webfa_doctor_reports_runtime_unreachable(monkeypatch, capsys):
    def fail_ensure_runtime(runtime_url=None, auto_start=True):
        raise RuntimeError("Runtime unreachable at http://127.0.0.1:65500")

    monkeypatch.setattr(cli, "ensure_runtime", fail_ensure_runtime)

    exit_code = cli.main_webfa(["doctor", "--runtime-url", "http://127.0.0.1:65500", "--no-auto-start"])

    assert exit_code == 1
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "fail"
    assert any(check["name"] == "doctor" for check in body["checks"])


def test_doctor_browser_loop_uses_web_object_runtime_surface(monkeypatch):
    calls = []

    class FakeRuntimeClient:
        def __init__(self, *, base_url, agent_id):
            calls.append(("init", base_url, agent_id))

        def open_url(self, url):
            calls.append(("open_url", url))
            return {"state": {"title": "WebFA Doctor"}}

        def observe(self, payload):
            calls.append(("observe", payload))
            if payload["mode"] == "page":
                return {
                    "objects": [
                        {"id": "field-1", "role": "textbox", "version": 3},
                        {"id": "form-1", "role": "form", "version": 1},
                    ]
                }
            return {"objects": [{"id": "result-1", "role": "text", "text": "Hello WebFA"}]}

        def browser_act(self, payload):
            calls.append(("act", payload))
            return {"ok": True}

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(cli, "WebFARuntimeClient", FakeRuntimeClient)

    assert cli._run_browser_loop("http://127.0.0.1:8787") is True
    assert ("init", "http://127.0.0.1:8787", "webfa-doctor") in calls
    assert any(call[0] == "act" and call[1]["operation"] == "set_value" for call in calls)
    assert any(call[0] == "act" and call[1]["operation"] == "submit" for call in calls)
    assert calls[-1] == ("close",)


def test_webfa_login_invokes_login_window(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    def fake_login(target):
        return {"status": "ok", "site": target.site, "profile": "default", "profile_dir": str(target.profile_dir)}

    monkeypatch.setattr(cli, "run_login_window", fake_login)

    exit_code = cli.main_webfa(["login", "github"])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "ok"
    assert body["site"] == "github.com"
