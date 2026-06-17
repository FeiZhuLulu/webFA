"""Unit tests for GitHub token redaction."""

from providers.github.auth import redact_tokens


def test_redact_github_pat():
    text = "Token: github_pat_11AAAAAA00abcdefghij1234567890abcdefghijklmnop"
    result = redact_tokens(text)
    assert "github_pat_" not in result
    assert "[REDACTED]" in result


def test_redact_ghp():
    text = "ghp_1234567890abcdefghijklmnop"
    result = redact_tokens(text)
    assert "ghp_" not in result
    assert "[REDACTED]" in result


def test_redact_bearer():
    text = "Bearer ghp_1234567890abcdefghijklmnop"
    result = redact_tokens(text)
    assert "Bearer" not in result or "[REDACTED]" in result


def test_redact_authorization_header():
    text = "Authorization: Bearer ghp_1234567890abcdefghijklmnop"
    result = redact_tokens(text)
    assert "ghp_" not in result


def test_redact_preserves_normal_text():
    text = "Repository fei/webfa not found"
    result = redact_tokens(text)
    assert result == text


def test_redact_multiple_tokens():
    text = "ghp_1234567890abcdefghijklmnop and github_pat_11AAAAAA00abcdefghij1234567890abcdefghijklmnop"
    result = redact_tokens(text)
    assert "ghp_" not in result
    assert "github_pat_" not in result
    assert result.count("[REDACTED]") == 2
