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
from schemas.browser import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserContentBlock,
    BrowserState,
    BrowserOpenRequest,
    parse_browser_url_parts,
)


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


def test_browser_open_request_accepts_web_urls():
    req = BrowserOpenRequest(url="https://example.com")
    assert req.url == "https://example.com"


def test_browser_action_rejects_raw_selector_payload():
    try:
        BrowserActionRequest(action="click", selector="button")
    except Exception as exc:
        assert "extra" in str(exc).lower() or "not permitted" in str(exc).lower()
    else:
        raise AssertionError("raw selector payload must be rejected")


def test_browser_action_validates_required_fields():
    try:
        BrowserActionRequest(action="type", target="el_1")
    except Exception as exc:
        assert "type requires text" in str(exc)
    else:
        raise AssertionError("type without text must fail")


def test_browser_object_actions_validate_required_fields():
    BrowserActionRequest(action="fill_form", target="form_1", fields={"name": "Fei"})
    BrowserActionRequest(action="submit_form", target="form_1")
    BrowserActionRequest(action="follow_link", target="el_1")
    BrowserActionRequest(action="activate_control", target="el_1")
    BrowserActionRequest(action="choose_option", target="el_1", value="public")
    BrowserActionRequest(action="read_list", target="block_1")
    BrowserActionRequest(action="inspect_block", target="block_1")

    invalid = [
        {"action": "fill_form", "target": "form_1"},
        {"action": "submit_form"},
        {"action": "follow_link"},
        {"action": "activate_control"},
        {"action": "choose_option", "target": "el_1"},
        {"action": "read_list"},
        {"action": "inspect_block"},
    ]
    for payload in invalid:
        try:
            BrowserActionRequest(**payload)
        except Exception:
            continue
        raise AssertionError(f"payload should be invalid: {payload}")


def test_browser_action_result_data_is_optional():
    without_data = BrowserActionResult(ok=True, action="observe", state=BrowserState())
    assert without_data.data is None
    with_data = BrowserActionResult(ok=True, action="inspect_block", state=BrowserState(), data={"id": "block_1"})
    assert with_data.data == {"id": "block_1"}


def test_browser_url_parts_parse_query():
    parts = parse_browser_url_parts("https://github.com/search?q=text&type=repositories")
    assert parts.scheme == "https"
    assert parts.host == "github.com"
    assert parts.origin == "https://github.com"
    assert parts.path == "/search"
    assert parts.query == {"q": "text", "type": "repositories"}


def test_browser_url_parts_empty_query():
    parts = parse_browser_url_parts("https://github.com")
    assert parts.origin == "https://github.com"
    assert parts.path == ""
    assert parts.query == {}


def test_browser_content_block_basic_shape():
    block = BrowserContentBlock(id="block_1", type="heading", text="alpha/webfa-one", element_ids=["el_7"])
    assert block.id == "block_1"
    assert block.type == "heading"
    assert block.element_ids == ["el_7"]


def test_browser_content_block_rejects_unsupported_type():
    try:
        BrowserContentBlock(id="block_1", type="repository", text="x", element_ids=[])
    except Exception as exc:
        assert "repository" in str(exc).lower() or "type" in str(exc).lower()
    else:
        raise AssertionError("unsupported block type must be rejected")


def test_browser_content_block_forbids_html_dom_and_storage_keys():
    from pydantic import ValidationError

    for forbidden in ("html", "outerHTML", "innerHTML", "cookies", "localStorage", "sessionStorage"):
        try:
            BrowserContentBlock(id="block_1", type="paragraph", text="x", element_ids=[], **{forbidden: "y"})
        except ValidationError:
            continue
        raise AssertionError(f"{forbidden} must be rejected by BrowserContentBlock")
