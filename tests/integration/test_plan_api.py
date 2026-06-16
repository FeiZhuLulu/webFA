"""Integration tests for Plan REST API."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_create_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {
                "owner": "mock-owner",
                "repo": "mock-repo",
                "issue_number": 1,
                "task_description": "Fix mock issue.",
            },
        })

    assert response.status_code == 201
    body = response.json()
    assert body["transaction_id"] == "mock.patch_and_open_pr"
    assert body["status"] == "pending_preview"
    assert body["risk"] == "high"
    assert body["plan_hash"].startswith("sha256:")
    assert body["workspace_id"].startswith("workspace_")
    assert len(body["steps"]) == 6


def test_create_plan_unknown_transaction(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.post("/v1/plans", json={
            "transaction_id": "nonexistent.transaction",
            "input": {},
        })

    assert response.status_code == 400


def test_get_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        create_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {"owner": "test", "repo": "repo", "issue_number": 1, "task_description": "Fix."},
        })
        plan_id = create_resp.json()["id"]

        get_resp = client.get(f"/v1/plans/{plan_id}")

    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == plan_id
    assert body["status"] == "pending_preview"


def test_get_plan_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/plans/nonexistent_plan")

    assert response.status_code == 404


def test_preview_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create plan
        create_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {"owner": "mock-owner", "repo": "mock-repo", "issue_number": 1, "task_description": "Fix."},
        })
        assert create_resp.status_code == 201
        plan_id = create_resp.json()["id"]

        # Preview
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 200
        body = preview_resp.json()

        assert body["plan_id"] == plan_id
        assert body["status"] == "pending_approval"
        assert body["risk"] == "high"
        assert body["approval_required"] is True
        assert body["approval_id"].startswith("approval_")
        assert body["plan_hash"].startswith("sha256:")
        assert body["diff_hash"].startswith("sha256:")
        assert body["policy"]["allowed"] is True
        assert body["preview"]["provider"] == "mock"
        assert len(body["preview"]["changed_files"]) == 1


def test_preview_plan_blocked_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # Create plan with blocked path in input
        create_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {
                "owner": "mock-owner",
                "repo": "mock-repo",
                "issue_number": 1,
                "task_description": "Fix.",
                "blocked_paths": ["src/**"],
            },
        })
        plan_id = create_resp.json()["id"]

        # Preview should fail because src/example.py matches src/**
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 400


def test_preview_plan_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.post("/v1/plans/nonexistent/preview")
    assert response.status_code == 404
