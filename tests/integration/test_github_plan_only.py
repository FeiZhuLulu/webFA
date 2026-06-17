"""Integration tests: GitHub plan-only readiness in P3."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_github_plan_creates_plan_only(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.post("/v1/plans", json={
            "transaction_id": "github.patch_and_open_pr",
            "input": {"owner": "fei", "repo": "webfa", "issue_number": 17, "task_description": "Fix issue"},
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "plan_only"
        assert body["transaction_id"] == "github.patch_and_open_pr"


def test_github_plan_only_preview_no_approval(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create plan
        plan_resp = client.post("/v1/plans", json={
            "transaction_id": "github.patch_and_open_pr",
            "input": {"owner": "fei", "repo": "webfa", "issue_number": 17, "task_description": "Fix issue"},
        })
        plan_id = plan_resp.json()["id"]

        # Preview
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 200
        body = preview_resp.json()
        assert body["status"] == "plan_only_preview"
        assert body["approval_required"] is False
        assert body["approval_id"] is None


def test_github_plan_only_execute_denied(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create plan
        plan_resp = client.post("/v1/plans", json={
            "transaction_id": "github.patch_and_open_pr",
            "input": {"owner": "fei", "repo": "webfa", "issue_number": 17, "task_description": "Fix issue"},
        })
        plan_id = plan_resp.json()["id"]

        # Try execute (should fail)
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": "fake_token",
        })
        assert exec_resp.status_code in (400, 403)


def test_mock_transaction_still_works(monkeypatch, tmp_path: Path):
    """Verify mock transactions still work normally after P3 changes."""
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create mock plan
        plan_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Test"},
        })
        assert plan_resp.status_code == 201
        assert plan_resp.json()["status"] == "pending_preview"

        plan_id = plan_resp.json()["id"]

        # Preview
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 200
        assert preview_resp.json()["approval_required"] is True
        approval_id = preview_resp.json()["approval_id"]

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
        assert exec_resp.json()["status"] == "verified"
