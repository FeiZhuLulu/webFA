from __future__ import annotations

import json
import tomllib
from pathlib import Path

from apps.runtime import cli


def test_pyproject_declares_console_scripts():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["webfa"] == "apps.runtime.cli:main_webfa"
    assert scripts["webfa-runtime"] == "apps.runtime.cli:main_runtime"
    assert scripts["webfa-mcp"] == "apps.runtime.cli:main_mcp"


def test_webfa_mcp_config_prints_installed_command(capsys):
    exit_code = cli.main_webfa(["mcp-config", "--runtime-url", "http://127.0.0.1:8787"])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    entry = body["mcpServers"]["webfa"]
    assert entry["command"] == "webfa-mcp"
    assert entry["env"]["WEBFA_RUNTIME_URL"] == "http://127.0.0.1:8787"


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

