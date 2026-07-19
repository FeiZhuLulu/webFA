from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


CURRENT_EVIDENCE = (
    "README.md",
    "README.en.md",
    "SECURITY.md",
    "RELEASE_CHECKLIST.md",
    "docs/OPEN_SOURCE_READINESS.md",
    "docs/browser-runtime-roadmap.md",
    "docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md",
    "docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md",
    "docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md",
    "docs/reports/P10_FINAL_ACCEPTANCE_REPORT.md",
    "docs/reports/P11_FINAL_ACCEPTANCE_REPORT.md",
    "docs/reports/P12_8_CORE_FINAL_ACCEPTANCE_MAINTENANCE_REVIEW.md",
    "docs/reports/PROFILE_BOOTSTRAP_ADVERSARIAL_REVIEW.md",
    "docs/reports/UI1B_PHASE_6_MAINTENANCE_REVIEW.md",
    "docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md",
)


MAINTAINED_GATES = (
    "tests/integration/test_mcp_stdio_browser.py",
    "tests/integration/test_managed_chromium_driver.py",
    "tests/integration/test_web_object_api.py",
    "tests/integration/test_profile_storage_isolation.py",
    "tests/integration/test_runtime_supervisor_multi_session.py",
    "tests/integration/test_profile_bootstrap_chromium.py",
    "tests/contract/test_mcp_security_contract.py",
    "tests/contract/test_web_object_security_contract.py",
    "tests/contract/test_python_packaging_contract.py",
    "tests/contract/test_desktop_distribution_contract.py",
    "scripts/audit-source-ui.cjs",
    "scripts/audit-installed-ui.cjs",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_current_evidence_and_maintained_gates_exist() -> None:
    missing = [
        path
        for path in (*CURRENT_EVIDENCE, *MAINTAINED_GATES)
        if not (ROOT / path).is_file()
    ]
    assert missing == []


def test_report_index_defines_point_in_time_authority() -> None:
    index = _read("docs/reports/README.md")
    assert "point-in-time engineering evidence" in index
    assert "older passing report is not a release certificate" in index
    assert "P1–P3 transaction-gateway evidence" in index
    assert "lightweight Runtime Manager" in index


def test_matrix_preserves_product_and_phase_boundaries() -> None:
    matrix = _read("docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md")
    assert "P1–P3 are completed\nhistorical transaction-gateway work" in matrix
    assert "P13 Durable Trace / Resume is not implemented" in matrix
    assert "no planner, memory, model, task loop, or Agent orchestration" in matrix
    assert "Source/wheel developer-preview baseline is distinct" in matrix


def test_public_status_consistently_defers_p13() -> None:
    for path in (
        "README.md",
        "README.en.md",
        "SECURITY.md",
        "RELEASE_CHECKLIST.md",
        "docs/OPEN_SOURCE_READINESS.md",
    ):
        text = _read(path)
        assert "P13" in text
        assert "defer" in text.lower() or "暂缓" in text


def test_historical_roadmap_cannot_claim_an_active_old_phase() -> None:
    historical = _read("docs/roadmap/stage-roadmap-and-frozen-constraints.md")
    current = _read("docs/browser-runtime-roadmap.md")
    entry = _read("docs/agent-entry-package.md")
    assert "状态：active" not in historical
    assert "it is complete below" in current
    assert "current P4-P12 agent-native local\nRuntime" in entry
    assert "P1-P3 transaction components remain packaged" in entry
