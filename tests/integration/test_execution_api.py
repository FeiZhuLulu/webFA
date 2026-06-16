"""Integration tests for Execution REST API."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def _full_flow(client):
    """Helper: create plan -> preview -> approve -> return (plan_id, approval_token)."""
    # Create plan
    resp = client.post("/v1/plans", json={
        "transaction_id": "mock.patch_and_open_pr",
        "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Fix."},
    })
    plan_id = resp.json()["id"]

    # Preview
    preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
    approval_id = preview_resp.json()["approval_id"]

    # Approve
    approve_resp = client.post(f"/v1/approvals/{approval_id}/approve")
    approval_token = approve_resp.json()["approval_token"]

    return plan_id, approval_token


def test_execute_without_approval_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create plan
        resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Fix."},
        })
        plan_id = resp.json()["id"]

        # Try execute without approval
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": "fake_token",
        })

    assert exec_resp.status_code == 403


def test_execute_with_approval_succeeds(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        plan_id, approval_token = _full_flow(client)

        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
        })

    assert exec_resp.status_code == 201
    body = exec_resp.json()
    assert body["status"] == "verified"
    assert body["plan_id"] == plan_id
    assert len(body["steps"]) == 3
    assert body["result"]["pr_url"].startswith("mock://github/")
    assert body["result"]["commit_sha"].startswith("commit_")


def test_get_execution(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        plan_id, approval_token = _full_flow(client)
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
        })
        execution_id = exec_resp.json()["id"]

        get_resp = client.get(f"/v1/executions/{execution_id}")

    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == execution_id
    assert body["status"] == "verified"


def test_get_execution_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.get("/v1/executions/nonexistent")

    assert resp.status_code == 404


def test_idempotency_key(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        plan_id, approval_token = _full_flow(client)

        resp1 = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
            "idempotency_key": "demo-001",
        })
        resp2 = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
            "idempotency_key": "demo-001",
        })

    assert resp1.json()["id"] == resp2.json()["id"]


def test_execution_generates_proof(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        plan_id, approval_token = _full_flow(client)
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
        })
        body = exec_resp.json()
        proof_id = body["proof_id"]

        assert proof_id is not None
        assert proof_id.startswith("proof_")

        # Get proof via API
        proof_resp = client.get(f"/v1/proofs/{proof_id}")
        assert proof_resp.status_code == 200
        proof = proof_resp.json()
        assert proof["provider"] == "mock"
        assert proof["proof"]["verification"]["passed"] is True
        assert proof["hash"].startswith("sha256:")
