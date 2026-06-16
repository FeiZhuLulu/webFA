"""Unit tests for Pydantic schemas."""

from schemas.common import (
    ChangedFile,
    PolicyResult,
    PolicyViolation,
    RiskFlag,
    VerificationCheck,
    VerificationResult,
)
from schemas.plan import (
    CreatePlanRequest,
    PlanRead,
    PlanPreview,
    PlanStep,
    PlanTarget,
    PreviewDetail,
)
from schemas.approval import (
    ApprovalApproveRequest,
    ApprovalApproveResult,
    ApprovalPayload,
    ApprovalRead,
    ApprovalRejectRequest,
    ApprovalRejectResult,
)
from schemas.execution import (
    ExecuteRequest,
    ExecutionRead,
    ExecutionStepRead,
)
from schemas.proof import (
    ProofBundle,
    ProofHashes,
    ProofRead,
    ProofResource,
)
from schemas.audit import AuditEventRead, AuditListResponse
from schemas.workspace import WorkspaceRead


def test_create_plan_request():
    req = CreatePlanRequest(transaction_id="mock.patch_and_open_pr", input={"owner": "test"})
    assert req.transaction_id == "mock.patch_and_open_pr"
    assert req.input["owner"] == "test"


def test_plan_read():
    p = PlanRead(
        id="plan_1",
        workspace_id="ws_1",
        transaction_id="mock.patch_and_open_pr",
        risk="high",
        plan_hash="sha256:abc",
        status="pending_preview",
    )
    assert p.id == "plan_1"
    assert p.status == "pending_preview"


def test_plan_preview():
    preview = PlanPreview(
        plan_id="plan_1",
        status="pending_approval",
        risk="high",
        approval_required=True,
        approval_id="approval_1",
        plan_hash="sha256:abc",
        diff_hash="sha256:def",
        policy=PolicyResult(allowed=True, approval_required=True),
        preview=PreviewDetail(
            provider="mock",
            target="mock-owner/mock-repo",
            changed_files=[ChangedFile(path="src/example.py", additions=12, deletions=3)],
            diff_summary="+12 -3",
        ),
    )
    assert preview.approval_required is True
    assert len(preview.preview.changed_files) == 1


def test_approval_payload():
    payload = ApprovalPayload(
        provider="mock",
        transaction="mock.patch_and_open_pr",
        target="mock-owner/mock-repo",
        risk="high",
        proof_types=["transport", "resource", "state"],
    )
    assert payload.provider == "mock"
    assert len(payload.proof_types) == 3


def test_approval_read():
    a = ApprovalRead(
        id="approval_1",
        plan_id="plan_1",
        status="pending",
        approval_level="user",
        plan_hash="sha256:abc",
    )
    assert a.status == "pending"


def test_execute_request():
    req = ExecuteRequest(
        plan_id="plan_1",
        approval_token="approval_token_abc123",
        idempotency_key="demo-001",
    )
    assert req.plan_id == "plan_1"


def test_execution_read():
    e = ExecutionRead(
        id="exec_1",
        plan_id="plan_1",
        status="verified",
        proof_id="proof_1",
        steps=[
            ExecutionStepRead(step_name="mock.branch.create", status="succeeded"),
        ],
    )
    assert e.status == "verified"
    assert len(e.steps) == 1


def test_proof_bundle():
    bundle = ProofBundle(
        provider="mock",
        transaction_id="mock.patch_and_open_pr",
        plan_id="plan_1",
        execution_id="exec_1",
        resource=ProofResource(type="mock_pull_request", id="mock_pr_1"),
        hashes=ProofHashes(plan_hash="sha256:abc", proof_hash="sha256:def"),
        verification=VerificationResult(passed=True, checks=[
            VerificationCheck(name="mock_branch_exists", passed=True),
        ]),
    )
    assert bundle.verification.passed is True


def test_proof_read():
    p = ProofRead(
        id="proof_1",
        execution_id="exec_1",
        provider="mock",
        proof_type="state",
    )
    assert p.provider == "mock"


def test_audit_event_read():
    a = AuditEventRead(
        id="audit_1",
        event_type="plan.created",
        event_payload={"plan_id": "plan_1"},
    )
    assert a.event_type == "plan.created"


def test_audit_list_response():
    resp = AuditListResponse(items=[
        AuditEventRead(id="a1", event_type="plan.created"),
        AuditEventRead(id="a2", event_type="approval.approved"),
    ])
    assert len(resp.items) == 2


def test_workspace_read():
    w = WorkspaceRead(id="ws_1", title="Fix issue #17", status="created")
    assert w.id == "ws_1"
