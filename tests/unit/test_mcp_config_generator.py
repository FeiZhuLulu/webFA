"""Unit tests for MCP config generator."""

import pytest

from apps.runtime.mcp.config_generator import generate_config, generate_config_json


def test_generate_config_has_mcpServers():
    config = generate_config(runtime_url="http://127.0.0.1:8787")
    assert "mcpServers" in config
    assert "webfa" in config["mcpServers"]


def test_generate_config_has_command():
    config = generate_config(runtime_url="http://127.0.0.1:8787")
    entry = config["mcpServers"]["webfa"]
    assert entry["command"] == "webfa-mcp"
    assert entry["args"] == []


def test_generate_config_source_mode_has_python_module_command():
    config = generate_config(runtime_url="http://127.0.0.1:8787", installed=False)
    entry = config["mcpServers"]["webfa"]
    assert "-m" in entry["args"]
    assert "apps.runtime.mcp.server" in entry["args"]


def test_generate_config_has_env():
    config = generate_config(runtime_url="http://127.0.0.1:8787")
    env = config["mcpServers"]["webfa"]["env"]
    assert env["WEBFA_RUNTIME_URL"] == "http://127.0.0.1:8787"
    assert env["WEBFA_AGENT_ID"] == "external-agent"


def test_generate_config_accepts_agent_id():
    config = generate_config(runtime_url="http://127.0.0.1:8787", agent_id="opencode")
    env = config["mcpServers"]["webfa"]["env"]
    assert env["WEBFA_AGENT_ID"] == "opencode"


def test_generate_config_opencode_shape():
    config = generate_config(runtime_url="http://127.0.0.1:8787", agent_id="opencode", client="opencode")
    entry = config["mcp"]["webfa"]
    assert entry["type"] == "local"
    assert entry["enabled"] is True
    assert entry["command"] == ["webfa-mcp"]
    assert entry["environment"]["WEBFA_RUNTIME_URL"] == "http://127.0.0.1:8787"
    assert entry["environment"]["WEBFA_AGENT_ID"] == "opencode"


def test_generate_config_json():
    json_str = generate_config_json(runtime_url="http://127.0.0.1:8787")
    assert "mcpServers" in json_str
    assert "webfa" in json_str


def test_generate_config_with_cwd():
    config = generate_config(runtime_url="http://127.0.0.1:8787", cwd="/path/to/webfa")
    assert config["mcpServers"]["webfa"]["cwd"] == "/path/to/webfa"


def test_generate_config_uses_packaged_multicall_sidecar(monkeypatch):
    monkeypatch.setenv("WEBFA_MCP_COMMAND", "C:/Program Files/WebFA/webfa.exe")
    monkeypatch.setenv("WEBFA_MCP_ARGS_JSON", '["mcp"]')

    config = generate_config(runtime_url="http://127.0.0.1:8787")

    entry = config["mcpServers"]["webfa"]
    assert entry["command"] == "C:/Program Files/WebFA/webfa.exe"
    assert entry["args"] == ["mcp"]


def test_generate_config_detects_frozen_multicall_sidecar(monkeypatch):
    monkeypatch.delenv("WEBFA_MCP_COMMAND", raising=False)
    monkeypatch.setattr("apps.runtime.mcp.config_generator.sys.frozen", True, raising=False)
    monkeypatch.setattr("apps.runtime.mcp.config_generator.sys.executable", "C:/WebFA/webfa.exe")

    config = generate_config(runtime_url="http://127.0.0.1:9123")

    entry = config["mcpServers"]["webfa"]
    assert entry["command"] == "C:/WebFA/webfa.exe"
    assert entry["args"] == ["mcp"]


def test_generate_config_rejects_invalid_packaged_sidecar_args(monkeypatch):
    monkeypatch.setenv("WEBFA_MCP_COMMAND", "C:/Program Files/WebFA/webfa.exe")
    monkeypatch.setenv("WEBFA_MCP_ARGS_JSON", '{"not": "an array"}')

    with pytest.raises(ValueError, match="JSON string array"):
        generate_config()
