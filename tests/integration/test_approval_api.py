"""Integration tests for Approval REST API."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def _create_plan_and_preview(client):
    """Helper: create plan, preview, return plan_id and approval_id."""
    resp = client.post("/v1/plans", json={
        "transaction_id": "mock.patch_and_open_pr",
        "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Fix."},
    })
    plan_id = resp.json()["id"]
    preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
    approval_id = preview_resp.json()["approval_id"]
    return plan_id, approval_id


def test_list_approvals(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        _create_plan_and_preview(client)
        resp = client.get("/v1/approvals")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["status"] == "pending"


def test_get_approval(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        _, approval_id = _create_plan_and_preview(client)
        resp = client.get(f"/v1/approvals/{approval_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == approval_id
    assert body["status"] == "pending"
    assert body["approval_level"] == "user"


def test_approve(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        _, approval_id = _create_plan_and_preview(client)
        resp = client.post(f"/v1/approvals/{approval_id}/approve", json={"user_note": "LGTM"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["approval_token"].startswith("approval_token_")


def test_reject(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        _, approval_id = _create_plan_and_preview(client)
        resp = client.post(f"/v1/approvals/{approval_id}/reject", json={"reason": "Not needed"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"


def test_approve_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        resp = client.post("/v1/approvals/nonexistent/approve")

    assert resp.status_code == 404
