"""Integration test: full mock transaction flow from plan to audit."""

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_full_mock_transaction_flow(monkeypatch, tmp_path: Path):
    """Complete flow: create plan -> preview -> approve -> execute -> verify -> proof -> audit."""
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        # 1. Create plan
        plan_resp = client.post("/v1/plans", json={
            "transaction_id": "mock.patch_and_open_pr",
            "input": {
                "owner": "mock-owner",
                "repo": "mock-repo",
                "issue_number": 1,
                "task_description": "Fix mock issue and open a draft PR.",
            },
        })
        assert plan_resp.status_code == 201
        plan = plan_resp.json()
        plan_id = plan["id"]
        assert plan["status"] == "pending_preview"

        # 2. Preview
        preview_resp = client.post(f"/v1/plans/{plan_id}/preview")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        approval_id = preview["approval_id"]
        assert preview["status"] == "pending_approval"
        assert preview["approval_required"] is True
        assert preview["diff_hash"].startswith("sha256:")
        assert preview["policy"]["allowed"] is True

        # 3. Execute without approval -> should fail
        exec_fail_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": "fake_token",
        })
        assert exec_fail_resp.status_code == 403

        # 4. Approve
        approve_resp = client.post(f"/v1/approvals/{approval_id}/approve")
        assert approve_resp.status_code == 200
        approval_token = approve_resp.json()["approval_token"]
        assert approve_resp.json()["status"] == "approved"

        # 5. Execute
        exec_resp = client.post("/v1/executions", json={
            "plan_id": plan_id,
            "approval_token": approval_token,
        })
        assert exec_resp.status_code == 201
        execution = exec_resp.json()
        assert execution["status"] == "verified"
        assert len(execution["steps"]) == 3
        assert execution["result"]["pr_url"].startswith("mock://github/")
        proof_id = execution["proof_id"]
        assert proof_id is not None

        # 6. Get execution
        get_exec_resp = client.get(f"/v1/executions/{execution['id']}")
        assert get_exec_resp.status_code == 200
        assert get_exec_resp.json()["status"] == "verified"

        # 7. Get proof
        proof_resp = client.get(f"/v1/proofs/{proof_id}")
        assert proof_resp.status_code == 200
        proof = proof_resp.json()
        assert proof["provider"] == "mock"
        assert proof["proof"]["verification"]["passed"] is True
        assert proof["hash"].startswith("sha256:")

        # 8. Get audits (workspace.created has no plan_id, query by workspace_id)
        workspace_id = plan["workspace_id"]
        audits_resp = client.get("/v1/audits", params={"workspace_id": workspace_id})
        assert audits_resp.status_code == 200
        events = audits_resp.json()["items"]
        event_types = [e["event_type"] for e in events]

        # Verify complete event chain
        expected_events = [
            "workspace.created",
            "plan.created",
            "plan.previewed",
            "policy.checked",
            "approval.created",
            "execution.created",
            "execution.started",
            "execution.step.started",
            "execution.step.succeeded",
            "execution.verifying",
            "proof.created",
            "execution.verified",
            "approval.approved",
        ]
        for expected in expected_events:
            assert expected in event_types, f"Missing audit event: {expected}"

        # Verify no sensitive data in audit payloads
        for event in events:
            payload = event["event_payload"]
            payload_str = str(payload).lower()
            assert "approval_token" not in payload_str or "[REDACTED]" in payload_str
