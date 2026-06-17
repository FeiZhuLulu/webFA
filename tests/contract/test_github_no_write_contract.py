"""Contract tests: GitHub adapter must be read-only, no write methods."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_github_adapter_no_write_methods():
    """GitHub adapter must not contain write method names."""
    source = (ROOT / "packages/providers/github/adapter.py").read_text(encoding="utf-8")
    forbidden = [
        "create_branch",
        "create_ref",
        "create_tree",
        "create_commit",
        "update_ref",
        "create_pull_request",
        "update_file",
        "delete_file",
        "merge_pull_request",
        "create_issue_comment",
    ]
    for name in forbidden:
        assert name not in source, f"Forbidden write method '{name}' found in GitHub adapter"


def test_github_no_write_routes():
    """GitHub API routes must not contain write endpoints."""
    source = (ROOT / "apps/runtime/api/routes/github.py").read_text(encoding="utf-8")
    forbidden = ["POST", "PUT", "PATCH", "DELETE"]
    for method in forbidden:
        # Check for route decorators with write methods
        assert f"@router.{method.lower()}" not in source, f"Forbidden {method} route found in GitHub routes"


def test_github_no_write_capabilities():
    """GitHub capabilities must not include write capabilities."""
    cap_file = ROOT / "resources/capabilities/github.read.yaml"
    if cap_file.exists():
        source = cap_file.read_text(encoding="utf-8")
        assert "mode: write" not in source
        assert "mode: read" in source


def test_github_connection_no_token_in_response():
    """GitHub connection response must not contain raw token."""
    source = (ROOT / "apps/runtime/api/routes/provider_connections.py").read_text(encoding="utf-8")
    # Response should not return the token
    assert '"token"' not in source or "token_stored" in source


def test_github_adapter_is_read_only_class():
    """Verify the adapter class name indicates read-only."""
    source = (ROOT / "packages/providers/github/adapter.py").read_text(encoding="utf-8")
    assert "ReadOnlyAdapter" in source or "read_only" in source.lower() or "ReadOnly" in source
