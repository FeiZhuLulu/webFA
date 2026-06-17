"""GitHub read-only adapter: reads repo/issue/tree/file context."""

from __future__ import annotations

import base64
from typing import Any

from providers.github.client import GitHubClient, GitHubClientError
from schemas.github import (
    GitHubBranch,
    GitHubFile,
    GitHubIssue,
    GitHubIssueComment,
    GitHubRateLimit,
    GitHubRepository,
    GitHubTree,
    GitHubTreeItem,
    GitHubViewer,
)


class GitHubReadOnlyAdapter:
    """Read-only GitHub adapter. No write operations."""

    provider = "github"

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def get_viewer(self) -> GitHubViewer:
        data = self._client.get("/user")
        return GitHubViewer(
            login=data["login"],
            id=data["id"],
            type=data.get("type", "User"),
        )

    def get_repo(self, owner: str, repo: str) -> GitHubRepository:
        data = self._client.get(f"/repos/{owner}/{repo}")
        return GitHubRepository(
            full_name=data["full_name"],
            name=data["name"],
            owner=data["owner"]["login"],
            default_branch=data.get("default_branch", "main"),
            private=data.get("private", False),
            description=data.get("description"),
            html_url=data.get("html_url"),
        )

    def get_default_branch(self, owner: str, repo: str) -> GitHubBranch:
        repo_data = self.get_repo(owner, repo)
        return self.get_branch(owner, repo, repo_data.default_branch)

    def get_branch(self, owner: str, repo: str, branch: str) -> GitHubBranch:
        data = self._client.get(f"/repos/{owner}/{repo}/branches/{branch}")
        return GitHubBranch(
            name=data["name"],
            sha=data["commit"]["sha"],
            protected=data.get("protected", False),
        )

    def get_tree(self, owner: str, repo: str, ref: str, recursive: bool = False) -> GitHubTree:
        params = {"ref": ref}
        if recursive:
            params["recursive"] = "1"
        data = self._client.get(f"/repos/{owner}/{repo}/git/trees/{ref}", params=params)
        items = [
            GitHubTreeItem(
                path=item["path"],
                mode=item.get("mode", ""),
                type=item.get("type", ""),
                sha=item.get("sha", ""),
                size=item.get("size"),
            )
            for item in data.get("tree", [])
        ]
        return GitHubTree(
            sha=data.get("sha", ""),
            truncated=data.get("truncated", False),
            items=items,
        )

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> GitHubFile:
        data = self._client.get(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        content = ""
        if data.get("content"):
            encoding = data.get("encoding", "base64")
            if encoding == "base64":
                try:
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                except Exception:
                    content = ""
            else:
                content = data["content"]
        return GitHubFile(
            path=data.get("path", path),
            sha=data.get("sha", ""),
            size=data.get("size", 0),
            content=content,
            encoding="utf-8",
            url=data.get("html_url"),
        )

    def get_issue(self, owner: str, repo: str, issue_number: int) -> GitHubIssue:
        data = self._client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            state=data.get("state", "open"),
            user=data.get("user", {}).get("login"),
            html_url=data.get("html_url"),
            labels=[l["name"] for l in data.get("labels", []) if isinstance(l, dict)],
        )

    def get_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[GitHubIssueComment]:
        data = self._client.get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        return [
            GitHubIssueComment(
                id=c["id"],
                user=c.get("user", {}).get("login"),
                body=c.get("body", ""),
                created_at=c.get("created_at"),
                html_url=c.get("html_url"),
            )
            for c in data
        ]

    def get_rate_limit(self) -> dict[str, Any]:
        return self._client.get("/rate_limit")
