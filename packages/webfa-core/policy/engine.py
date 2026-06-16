"""Policy Engine v0: hardcoded rules for Phase 1."""

from __future__ import annotations

import fnmatch

from schemas.common import ChangedFile, PolicyResult, PolicyViolation, RiskFlag


# Default blocked paths (from v0 方案)
DEFAULT_BLOCKED_PATHS: list[str] = [
    ".github/workflows/**",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
    "**/secrets/**",
]

MAX_FILES = 5
MAX_DIFF_LINES = 800


def _matches_blocked(path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any blocked pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


class PolicyEngine:
    """Hardcoded policy checks for Phase 1."""

    def check(
        self,
        transaction_id: str,
        provider: str,
        risk: str,
        changed_files: list[ChangedFile],
        diff_text: str,
        blocked_paths: list[str] | None = None,
    ) -> PolicyResult:
        effective_blocked = blocked_paths if blocked_paths is not None else DEFAULT_BLOCKED_PATHS
        violations: list[PolicyViolation] = []
        risk_flags: list[RiskFlag] = []

        # 1. Check blocked paths
        for cf in changed_files:
            if _matches_blocked(cf.path, effective_blocked):
                violations.append(PolicyViolation(
                    code="blocked_path",
                    message=f"File '{cf.path}' matches a blocked path pattern.",
                    path=cf.path,
                ))

        # 2. Check file count
        if len(changed_files) > MAX_FILES:
            violations.append(PolicyViolation(
                code="too_many_files",
                message=f"Changed {len(changed_files)} files, max is {MAX_FILES}.",
            ))

        # 3. Check diff line count
        diff_lines = len(diff_text.splitlines()) if diff_text else 0
        if diff_lines > MAX_DIFF_LINES:
            violations.append(PolicyViolation(
                code="diff_too_large",
                message=f"Diff has {diff_lines} lines, max is {MAX_DIFF_LINES}.",
            ))

        # 4. Risk flags
        if risk in ("medium", "high", "critical"):
            risk_flags.append(RiskFlag(
                code="high_risk_write",
                message=f"Transaction '{transaction_id}' is rated '{risk}' and requires user approval.",
            ))

        allowed = len(violations) == 0
        approval_required = risk in ("medium", "high", "critical")

        return PolicyResult(
            allowed=allowed,
            approval_required=approval_required,
            risk_flags=risk_flags,
            blocked=violations,
        )
