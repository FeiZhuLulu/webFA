"""Integration tests for MCP-adjacent Runtime behavior.

The P4.5 MCP stdio browser flow lives in test_mcp_stdio_browser.py.
Legacy transaction flow remains covered here so old code stays isolated.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from apps.runtime.mcp.runtime_client import WebFARuntimeClient
from storage.db import reset_engine_for_tests


def test_legacy_transactions_endpoint_still_available(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Get the test server's base URL
        base_url = f"http://localhost:{client.app.server.port}" if hasattr(client.app, 'server') else "http://testserver"

        # Use the MCP runtime client against the test client's app
        # For integration test, we test the tools directly via HTTP
        resp = client.get("/v1/transactions")
        assert resp.status_code == 200
        txns = resp.json()["transactions"]
        ids = {t["id"] for t in txns}
        assert "mock.patch_and_open_pr" in ids

        resp = client.get("/v1/providers")
        assert resp.status_code == 200


def test_mcp_config_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/config")
        assert resp.status_code == 200
        config = resp.json()
        assert "mcpServers" in config
        assert "webfa" in config["mcpServers"]


def test_mcp_status_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/status")
        assert resp.status_code == 200
        status = resp.json()
        assert status["transport"] == "stdio"
        assert status["tools"] == [
            "webfa.open_url",
            "webfa.observe",
            "webfa.act",
            "webfa.get_tabs",
            "webfa.switch_tab",
        ]


def test_mcp_status_legacy_transaction_tools_are_opt_in(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_ENABLE_LEGACY_TRANSACTION", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/mcp/status")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        assert "webfa.open_url" in tools
        assert "webfa.plan" in tools
        assert "webfa.execute" in tools


def test_legacy_transaction_rest_flow(monkeypatch, tmp_path: Path):
    """Legacy transaction REST flow; not part of the P4.5 agent browser path."""
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    from apps.runtime.mcp.tools import tool_discover, tool_plan, tool_preview, tool_execute, tool_get_execution, tool_get_proof

    # We need to patch the runtime client to use the test client
    # For now, test via direct HTTP calls that mirror what tools do
    with TestClient(create_app()) as client:
        # Discover
        txns_resp = client.get("/v1/transactions")
        assert txns_resp.status_code == 200
        txns = txns_resp.json()["transactions"]
        assert any(t["id"] == "mock.patch_and_open_pr" for t in txns)

        # Plan
        plan_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "MCP test"},
        })
        assert plan_resp.status_code == 201
        plan = plan_resp.json()
        plan_id = plan["id"]

        # Preview
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        approval_id = preview["approval_id"]

        # Execute without approval -> should fail
        exec_fail = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": "fake",
        })
        assert exec_fail.status_code == 403

        # Approve
        approve_resp = client.post(f"/v1/approvals/{approval_id}/approve")
        assert approve_resp.status_code == 200
        token = approve_resp.json()["approval_token"]

        # Execute
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": token,
        })
        assert exec_resp.status_code == 201
        execution = exec_resp.json()
        assert execution["status"] == "verified"
        exec_id = execution["id"]
        proof_id = execution["proof_id"]

        # Get execution
        get_exec = client.get(f"/v1/executions/{exec_id}")
        assert get_exec.status_code == 200
        assert get_exec.json()["status"] == "verified"

        # Get proof
        get_proof = client.get(f"/v1/proofs/{proof_id}")
        assert get_proof.status_code == 200
        proof = get_proof.json()
        assert proof["provider"] == "mock"
        assert proof["proof"]["verification"]["passed"] is True
