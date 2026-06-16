"""Verification Service: verifies mock resources after execution."""

from __future__ import annotations

from typing import Any

from schemas.common import VerificationCheck, VerificationResult


class VerificationService:
    """Verifies that mock resources were created correctly."""

    def verify(
        self,
        execution_result: dict[str, Any],
        expected_diff_hash: str | None = None,
    ) -> VerificationResult:
        checks: list[VerificationCheck] = []

        # 1. Check branch exists (mock: always passes if result has branch)
        branch = execution_result.get("branch")
        checks.append(VerificationCheck(
            name="mock_branch_exists",
            passed=bool(branch),
            detail=f"branch={branch}" if branch else "no branch in result",
        ))

        # 2. Check commit exists (mock: always passes if result has commit_sha)
        commit_sha = execution_result.get("commit_sha")
        checks.append(VerificationCheck(
            name="mock_commit_exists",
            passed=bool(commit_sha),
            detail=f"sha={commit_sha}" if commit_sha else "no commit_sha in result",
        ))

        # 3. Check PR exists (mock: always passes if result has pr_url)
        pr_url = execution_result.get("pr_url")
        checks.append(VerificationCheck(
            name="mock_pr_exists",
            passed=bool(pr_url),
            detail=f"url={pr_url}" if pr_url else "no pr_url in result",
        ))

        # 4. Check diff_hash matches
        actual_diff_hash = execution_result.get("diff_hash")
        if expected_diff_hash:
            diff_match = actual_diff_hash == expected_diff_hash
        else:
            diff_match = bool(actual_diff_hash)
        checks.append(VerificationCheck(
            name="diff_hash_matches",
            passed=diff_match,
            detail=f"expected={expected_diff_hash}, actual={actual_diff_hash}",
        ))

        all_passed = all(c.passed for c in checks)
        return VerificationResult(passed=all_passed, checks=checks)
