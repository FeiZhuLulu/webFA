"""REST API: GitHub workspace import endpoint."""

from __future__ import annotations

import fnmatch
from typing import Any

from fastapi import APIRouter, HTTPException

from providers.github.adapter import GitHubReadOnlyAdapter
from providers.github.auth import GitHubAuth
from providers.github.client import GitHubClient, GitHubClientError
from providers.github.snapshots import create_snapshot
from schemas.github import GitHubWorkspaceImportRequest
from storage.credential_store import CredentialStore
from storage.db import session_scope
from storage.models import AuditEvent, Workspace, new_id

router = APIRouter()

# Default blocked paths from v0 方案
BLOCKED_PATHS = [
    ".github/workflows/**",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
    "**/secrets/**",
]


def _get_adapter() -> GitHubReadOnlyAdapter:
    auth = GitHubAuth(CredentialStore())
    try:
        token = auth.get_token()
    except FileNotFoundError:
        raise HTTPException(status_code=403, detail="GitHub not connected")
    return GitHubReadOnlyAdapter(GitHubClient(token))


def _is_blocked(path: str) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in BLOCKED_PATHS)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


@router.post("/github/workspaces/import", status_code=201)
def import_github_workspace(body: GitHubWorkspaceImportRequest):
    try:
        adapter = _get_adapter()

        # 1. Read repo metadata
        repo = adapter.get_repo(body.owner, body.repo)

        # 2. Read branch
        branch = adapter.get_branch(body.owner, body.repo, body.base_branch)

        # 3. Read tree
        tree = adapter.get_tree(body.owner, body.repo, branch.sha, recursive=True)

        # 4. Read issue
        issue = adapter.get_issue(body.owner, body.repo, body.issue_number)

        # 5. Read issue comments
        comments = adapter.get_issue_comments(body.owner, body.repo, body.issue_number)

        # 6. Select candidate files
        candidate_files = []
        for item in tree.items:
            if item.type != "blob":
                continue
            if _is_blocked(item.path):
                continue
            if body.candidate_paths and not _matches_any(item.path, body.candidate_paths):
                continue
            if item.size and item.size > body.max_file_bytes:
                continue
            candidate_files.append(item)
            if len(candidate_files) >= body.max_files:
                break

        # 7. Read candidate file contents
        read_files = []
        for item in candidate_files:
            try:
                f = adapter.get_file(body.owner, body.repo, item.path, branch.sha)
                read_files.append(f)
            except Exception:
                continue

        # 8. Create workspace + snapshots
        with session_scope() as session:
            workspace = Workspace(
                id=new_id("workspace"),
                title=f"{body.owner}/{body.repo}#{body.issue_number}: {issue.title[:100]}",
                user_goal=issue.title,
                status="github_context_imported",
                context_summary=f"Issue #{body.issue_number}: {issue.title}. {len(comments)} comments, {len(read_files)} files read.",
            )
            session.add(workspace)

            # Snapshot: repo metadata
            create_snapshot(
                session=session,
                workspace_id=workspace.id,
                provider="github",
                resource_type="github.repository",
                resource_id=repo.full_name,
                snapshot_data=repo.model_dump(),
                resource_url=repo.html_url,
                taint_level="external_github_metadata",
            )

            # Snapshot: issue
            create_snapshot(
                session=session,
                workspace_id=workspace.id,
                provider="github",
                resource_type="github.issue",
                resource_id=f"{body.owner}/{body.repo}#{body.issue_number}",
                snapshot_data=issue.model_dump(),
                resource_url=issue.html_url,
                taint_level="external_github_user_content",
            )

            # Snapshot: comments
            for c in comments:
                create_snapshot(
                    session=session,
                    workspace_id=workspace.id,
                    provider="github",
                    resource_type="github.issue_comment",
                    resource_id=f"{body.owner}/{body.repo}#{body.issue_number}/comment/{c.id}",
                    snapshot_data=c.model_dump(),
                    resource_url=c.html_url,
                    taint_level="external_github_user_content",
                )

            # Snapshot: files
            for f in read_files:
                create_snapshot(
                    session=session,
                    workspace_id=workspace.id,
                    provider="github",
                    resource_type="github.file",
                    resource_id=f"{body.owner}/{body.repo}/{f.path}@{branch.sha[:8]}",
                    snapshot_data=f.model_dump(),
                    resource_url=f.url,
                    taint_level="external_github_source_code",
                )

            # Audit
            session.add(AuditEvent(
                id=new_id("audit"),
                workspace_id=workspace.id,
                event_type="workspace.github_import.completed",
                event_payload_json={
                    "workspace_id": workspace.id,
                    "owner": body.owner,
                    "repo": body.repo,
                    "issue_number": body.issue_number,
                    "issue_title": issue.title,
                    "comments_count": len(comments),
                    "tree_files_count": len(tree.items),
                    "candidate_files_count": len(candidate_files),
                    "read_files_count": len(read_files),
                },
            ))

            return {
                "workspace_id": workspace.id,
                "provider": "github",
                "target": {
                    "owner": body.owner,
                    "repo": body.repo,
                    "issue_number": body.issue_number,
                    "base_branch": body.base_branch,
                },
                "status": "github_context_imported",
                "summary": {
                    "issue_title": issue.title,
                    "issue_state": issue.state,
                    "comments_count": len(comments),
                    "tree_files_count": len(tree.items),
                    "candidate_files_count": len(candidate_files),
                    "read_files_count": len(read_files),
                },
            }

    except GitHubClientError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=redact_tokens(str(e.message)))
