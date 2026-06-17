"""GitHub authentication: credential management and connection testing."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from providers.github.client import GitHubClient, GitHubClientError
from schemas.github import GitHubConnectionTestResult, GitHubRateLimit, GitHubViewer
from storage.credential_store import CredentialStore

# Patterns for token redaction
TOKEN_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"ghr_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer [A-Za-z0-9_-]{20,}"),
    re.compile(r"Authorization:\s*[A-Za-z0-9_-]{20,}", re.IGNORECASE),
]


def redact_tokens(text: str) -> str:
    """Redact GitHub tokens from text."""
    result = text
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


class GitHubAuth:
    """Manages GitHub credential storage and connection testing."""

    def __init__(self, credential_store: CredentialStore) -> None:
        self._store = credential_store

    def connect(self, token: str, resource_scope: dict[str, Any] | None = None) -> str:
        """Store token and return credential_ref."""
        return self._store.put("github", token, connection_id="default")

    def disconnect(self) -> bool:
        """Remove stored credential."""
        return self._store.delete("github:default")

    def get_token(self) -> str:
        """Get stored token. Raises if not found."""
        return self._store.get("github:default")

    def is_connected(self) -> bool:
        return self._store.exists("github:default")

    def test_connection(self) -> GitHubConnectionTestResult:
        """Test GitHub connection by calling /user."""
        try:
            token = self.get_token()
        except FileNotFoundError:
            return GitHubConnectionTestResult(
                status="disconnected",
                message="No GitHub token configured.",
            )

        try:
            client = GitHubClient(token)
            viewer_data = client.get("/user")
            viewer = GitHubViewer(
                login=viewer_data["login"],
                id=viewer_data["id"],
                type=viewer_data.get("type", "User"),
            )
            rate_data = client.get("/rate_limit")
            rate = rate_data.get("resources", {}).get("core", {})
            return GitHubConnectionTestResult(
                status="connected",
                viewer=viewer,
                message=f"Connected as {viewer.login}",
                rate_limit=GitHubRateLimit(
                    limit=rate.get("limit", 0),
                    remaining=rate.get("remaining", 0),
                    reset=rate.get("reset", 0),
                    used=rate.get("used", 0),
                ),
            )
        except GitHubClientError as e:
            status = "error"
            if e.status_code == 401:
                status = "invalid"
            elif e.status_code == 403:
                status = "insufficient_permissions"
            return GitHubConnectionTestResult(
                status=status,
                message=redact_tokens(str(e.message)),
            )
        except Exception as e:
            return GitHubConnectionTestResult(
                status="error",
                message=redact_tokens(str(e)),
            )
