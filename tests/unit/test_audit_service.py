"""Unit tests for AuditService and redaction."""

from audit.store import AuditService, redact_payload


def test_redact_token():
    payload = {"approval_token": "secret123", "plan_id": "plan_1"}
    redacted = redact_payload(payload)
    assert redacted["approval_token"] == "[REDACTED]"
    assert redacted["plan_id"] == "plan_1"


def test_redact_nested():
    payload = {"result": {"authorization_header": "Bearer xyz", "status": "ok"}}
    redacted = redact_payload(payload)
    assert redacted["result"]["authorization_header"] == "[REDACTED]"
    assert redacted["result"]["status"] == "ok"


def test_redact_credential():
    payload = {"credential_ref": "keyring://github", "provider": "mock"}
    redacted = redact_payload(payload)
    assert redacted["credential_ref"] == "[REDACTED]"
    assert redacted["provider"] == "mock"
