from __future__ import annotations

import httpx

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


def test_runtime_client_disables_env_proxy_for_loopback():
    client = WebFARuntimeClient(base_url="http://127.0.0.1:8787")

    assert isinstance(client._client, httpx.Client)
    assert client._client._trust_env is False


def test_runtime_client_keeps_env_proxy_behavior_for_remote_url():
    captured: dict[str, object] = {}

    class FakeClient:
        _trust_env = True

        def __init__(self, **kwargs):
            captured.update(kwargs)

    original_client = httpx.Client
    httpx.Client = FakeClient
    try:
        client = WebFARuntimeClient(base_url="https://example.com")
    finally:
        httpx.Client = original_client

    assert isinstance(client._client, FakeClient)
    assert "trust_env" not in captured
