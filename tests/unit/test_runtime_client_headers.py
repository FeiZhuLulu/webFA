from __future__ import annotations

from apps.runtime.mcp.runtime_client import WebFARuntimeClient


def test_runtime_client_sends_agent_id_header(monkeypatch):
    monkeypatch.setenv("WEBFA_AGENT_ID", "opencode")
    client = WebFARuntimeClient(base_url="http://127.0.0.1:8787")

    headers = client._headers("webfa.open_url")

    assert headers["X-WebFA-Caller"] == "mcp"
    assert headers["X-WebFA-Agent-Id"] == "opencode"
    assert headers["X-WebFA-MCP-Tool"] == "webfa.open_url"


def test_runtime_client_defaults_agent_id(monkeypatch):
    monkeypatch.delenv("WEBFA_AGENT_ID", raising=False)
    client = WebFARuntimeClient(base_url="http://127.0.0.1:8787")

    assert client._headers()["X-WebFA-Agent-Id"] == "anonymous-mcp"
