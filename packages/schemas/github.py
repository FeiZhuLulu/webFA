"""GitHub API response schemas (read-only)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GitHubViewer(BaseModel):
    login: str
    id: int
    type: str = "User"


class GitHubRepository(BaseModel):
    full_name: str
    name: str
    owner: str
    default_branch: str = "main"
    private: bool = False
    description: str | None = None
    html_url: str | None = None


class GitHubBranch(BaseModel):
    name: str
    sha: str
    protected: bool = False


class GitHubTreeItem(BaseModel):
    path: str
    mode: str = ""
    type: str = ""  # blob, tree
    sha: str = ""
    size: int | None = None


class GitHubTree(BaseModel):
    sha: str
    truncated: bool = False
    items: list[GitHubTreeItem] = Field(default_factory=list)


class GitHubFile(BaseModel):
    path: str
    sha: str
    size: int = 0
    content: str = ""  # decoded content
    encoding: str = "utf-8"
    url: str | None = None


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str | None = None
    state: str = "open"
    user: str | None = None
    html_url: str | None = None
    labels: list[str] = Field(default_factory=list)


class GitHubIssueComment(BaseModel):
    id: int
    user: str | None = None
    body: str = ""
    created_at: str | None = None
    html_url: str | None = None


class GitHubRateLimit(BaseModel):
    limit: int = 0
    remaining: int = 0
    reset: int = 0
    used: int = 0


class GitHubConnectionRequest(BaseModel):
    token: str
    resource_scope: dict[str, Any] = Field(default_factory=dict)


class GitHubConnectionResponse(BaseModel):
    provider: str = "github"
    status: str
    auth_mode: str = "fine_grained_pat"
    credential_ref: str
    last_verified_at: str | None = None
    token_stored: bool = True


class GitHubConnectionTestResult(BaseModel):
    provider: str = "github"
    status: str  # connected, invalid, insufficient_permissions, error
    viewer: GitHubViewer | None = None
    message: str = ""
    rate_limit: GitHubRateLimit | None = None


class GitHubWorkspaceImportRequest(BaseModel):
    owner: str
    repo: str
    issue_number: int
    base_branch: str = "main"
    candidate_paths: list[str] = Field(default_factory=lambda: ["src/**", "tests/**"])
    max_files: int = 20
    max_file_bytes: int = 200000


class GitHubWorkspaceImportResponse(BaseModel):
    workspace_id: str
    provider: str = "github"
    target: dict[str, Any] = Field(default_factory=dict)
    status: str = "github_context_imported"
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
