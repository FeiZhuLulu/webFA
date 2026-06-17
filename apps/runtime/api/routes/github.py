"""REST API: GitHub read-only endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from providers.github.adapter import GitHubReadOnlyAdapter
from providers.github.auth import GitHubAuth, redact_tokens
from providers.github.client import GitHubClient, GitHubClientError
from providers.github.snapshots import create_snapshot
from storage.credential_store import CredentialStore
from storage.db import session_scope
from storage.models import AuditEvent, new_id

router = APIRouter()


def _get_adapter() -> GitHubReadOnlyAdapter:
    auth = GitHubAuth(CredentialStore())
    try:
        token = auth.get_token()
    except FileNotFoundError:
        raise HTTPException(status_code=403, detail="GitHub not connected")
    client = GitHubClient(token)
    return GitHubReadOnlyAdapter(client)


def _github_error(e: GitHubClientError) -> HTTPException:
    code_map = {
        401: "github_bad_credentials",
        403: "github_forbidden",
        404: "github_resource_not_found",
        422: "github_validation_error",
    }
    code = code_map.get(e.status_code, "github_provider_error")
    if e.rate_limit and e.rate_limit.remaining == 0:
        code = "github_rate_limited"
    return HTTPException(
        status_code=e.status_code if e.status_code in (401, 403, 404) else 502,
        detail={"code": code, "message": redact_tokens(e.message)},
    )


@router.get("/github/repos/{owner}/{repo}")
def get_repo(owner: str, repo: str):
    try:
        adapter = _get_adapter()
        result = adapter.get_repo(owner, repo)
        with session_scope() as session:
            session.add(AuditEvent(
                id=new_id("audit"),
                event_type="github.repo.read",
                event_payload_json={"owner": owner, "repo": repo},
            ))
        return result.model_dump()
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/repos/{owner}/{repo}/branches/{branch}")
def get_branch(owner: str, repo: str, branch: str):
    try:
        adapter = _get_adapter()
        result = adapter.get_branch(owner, repo, branch)
        return result.model_dump()
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/repos/{owner}/{repo}/tree")
def get_tree(owner: str, repo: str, ref: str = "main", recursive: bool = False):
    try:
        adapter = _get_adapter()
        result = adapter.get_tree(owner, repo, ref, recursive)
        return result.model_dump()
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/repos/{owner}/{repo}/files")
def get_file(owner: str, repo: str, path: str, ref: str = "main"):
    try:
        adapter = _get_adapter()
        result = adapter.get_file(owner, repo, path, ref)
        return result.model_dump()
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/repos/{owner}/{repo}/issues/{issue_number}")
def get_issue(owner: str, repo: str, issue_number: int):
    try:
        adapter = _get_adapter()
        result = adapter.get_issue(owner, repo, issue_number)
        with session_scope() as session:
            session.add(AuditEvent(
                id=new_id("audit"),
                event_type="github.issue.read",
                event_payload_json={"owner": owner, "repo": repo, "issue_number": issue_number},
            ))
        return result.model_dump()
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/repos/{owner}/{repo}/issues/{issue_number}/comments")
def get_issue_comments(owner: str, repo: str, issue_number: int):
    try:
        adapter = _get_adapter()
        result = adapter.get_issue_comments(owner, repo, issue_number)
        with session_scope() as session:
            session.add(AuditEvent(
                id=new_id("audit"),
                event_type="github.issue_comments.read",
                event_payload_json={"owner": owner, "repo": repo, "issue_number": issue_number},
            ))
        return [c.model_dump() for c in result]
    except GitHubClientError as e:
        raise _github_error(e)


@router.get("/github/rate_limit")
def get_rate_limit():
    try:
        adapter = _get_adapter()
        result = adapter.get_rate_limit()
        return result
    except GitHubClientError as e:
        raise _github_error(e)
