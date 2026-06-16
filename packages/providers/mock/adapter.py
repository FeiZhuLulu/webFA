"""Mock Provider Adapter: simulates GitHub-like operations without network calls."""

from __future__ import annotations

import hashlib
from typing import Any


def _mock_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha256(seed.encode()).hexdigest()[:12]}"


class MockAdapter:
    """Simulates provider side effects. No external network calls."""

    provider = "mock"

    def read_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return {
            "number": issue_number,
            "title": f"Mock issue #{issue_number}",
            "body": f"This is a mock issue for {owner}/{repo}.",
            "state": "open",
        }

    def read_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "private": False,
        }

    def generate_diff(self, owner: str, repo: str, issue_number: int, task_description: str) -> str:
        return (
            f"--- a/src/example.py\n"
            f"+++ b/src/example.py\n"
            f"@@ -1,5 +1,14 @@\n"
            f" # {owner}/{repo} - fix for issue #{issue_number}\n"
            f"+import logging\n"
            f"+\n"
            f"+logger = logging.getLogger(__name__)\n"
            f"+\n"
            f" def main():\n"
            f"-    pass\n"
            f"+    logger.info('Fix applied')\n"
            f"+    return True\n"
            f"+\n"
            f"+\n"
            f"+def test_main():\n"
            f"+    assert main() is True\n"
        )

    def create_branch(self, owner: str, repo: str, branch_name: str, plan_seed: str) -> dict[str, Any]:
        branch_id = _mock_id("branch", plan_seed)
        return {
            "branch_id": branch_id,
            "name": branch_name,
            "ref": f"refs/heads/{branch_name}",
        }

    def create_commit(self, owner: str, repo: str, branch: str, message: str, plan_seed: str) -> dict[str, Any]:
        commit_sha = _mock_id("commit", plan_seed)
        return {
            "sha": commit_sha,
            "message": message,
            "branch": branch,
        }

    def create_pr(self, owner: str, repo: str, branch: str, title: str, plan_seed: str) -> dict[str, Any]:
        pr_number = int(hashlib.sha256(plan_seed.encode()).hexdigest()[:4], 16) % 1000
        return {
            "number": pr_number,
            "url": f"mock://github/{owner}/{repo}/pull/{pr_number}",
            "title": title,
            "state": "open",
            "draft": True,
            "head_branch": branch,
        }
