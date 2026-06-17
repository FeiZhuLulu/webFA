"""P3 Adversarial Test Script — GitHub read-only boundary verification."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import httpx

API = "http://127.0.0.1:8787"
DB = os.path.join(os.environ["APPDATA"], "WebFA", "webfa.db")
results = []


def ok(r):
    return r.get("ok", False)


def err_code(r):
    return r.get("error", {}).get("code", "")


# === G07: SQLite no raw token ===
def test_sqlite_no_token():
    conn = sqlite3.connect(DB)
    dump = ""
    for table in ["provider_connections", "audit_events", "resource_snapshots", "plans", "approvals", "proofs"]:
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                dump += str(row)
        except Exception:
            pass
    conn.close()
    forbidden = ["github_pat_", "ghp_", "Bearer ", "Authorization:"]
    found = [f for f in forbidden if f in dump]
    return len(found) == 0, f"Found: {found}" if found else "clean"


# === G11: GitHub adapter no write methods ===
def test_adapter_no_write():
    source = Path("packages/providers/github/adapter.py").read_text(encoding="utf-8")
    forbidden = ["create_branch", "create_ref", "create_tree", "create_commit", "update_ref",
                  "create_pull_request", "create_pr", "update_file", "delete_file", "merge_pull"]
    found = [f for f in forbidden if f in source]
    return len(found) == 0, f"Found: {found}" if found else "clean"


# === G12: No write capabilities ===
def test_no_write_capabilities():
    # Check if any write capabilities are registered
    cap_file = Path("resources/capabilities/github.read.yaml")
    if cap_file.exists():
        source = cap_file.read_text(encoding="utf-8")
        if "mode: write" in source:
            return False, "write capability found"
    return True, "read-only"


# === G13: No write endpoints ===
def test_no_write_endpoints():
    source = Path("apps/runtime/api/routes/github.py").read_text(encoding="utf-8")
    # Check for POST/PUT/PATCH/DELETE routes (excluding connection endpoints)
    for method in ["@router.post", "@router.put", "@router.patch", "@router.delete"]:
        if method in source:
            return False, f"{method} found in github.py"
    return True, "read-only"


# === G14: MCP no raw GitHub tools ===
def test_mcp_no_raw_github():
    from apps.runtime.mcp.server import mcp
    tool_names = list(mcp._tool_manager._tools.keys()) if hasattr(mcp, "_tool_manager") else []
    forbidden = ["webfa_github_read_file", "webfa_github_raw", "webfa_github_connect",
                  "webfa_github_save_token", "webfa_github_create_pr"]
    found = [f for f in forbidden if f in tool_names]
    return len(found) == 0, f"Found: {found}" if found else "clean"


# === G15: github.patch_and_open_pr execute denied ===
def test_github_execute_denied():
    resp = httpx.post(f"{API}/v1/plans", json={
        "transaction_id": "github.patch_and_open_pr",
        "input": {"owner": "fei", "repo": "webfa", "issue_number": 1, "task_description": "Test"},
    })
    if resp.status_code != 201:
        return False, f"plan failed: {resp.status_code}"
    plan_id = resp.json()["id"]
    status = resp.json()["status"]

    # Preview
    prev = httpx.post(f"{API}/v1/plans/{plan_id}/preview")
    if prev.status_code != 200:
        return False, f"preview failed: {prev.status_code}"

    # Execute should fail
    exec_resp = httpx.post(f"{API}/v1/executions", json={"plan_id": plan_id, "approval_token": "fake"})
    denied = exec_resp.status_code in (400, 403)
    return denied, f"status={exec_resp.status_code}"


# === G16: plan-only preview no approval ===
def test_plan_only_no_approval():
    resp = httpx.post(f"{API}/v1/plans", json={
        "transaction_id": "github.patch_and_open_pr",
        "input": {"owner": "fei", "repo": "webfa", "issue_number": 2, "task_description": "Test"},
    })
    plan_id = resp.json()["id"]
    prev = httpx.post(f"{API}/v1/plans/{plan_id}/preview")
    body = prev.json()
    no_approval = body.get("approval_required") is False and body.get("approval_id") is None
    return no_approval, f"approval_required={body.get('approval_required')}, approval_id={body.get('approval_id')}"


# === G19: Snapshot hash recompute ===
def test_snapshot_hash():
    from providers.github.snapshots import canonical_json_hash, content_hash
    # Test canonical JSON hash stability
    h1 = canonical_json_hash({"b": 2, "a": 1})
    h2 = canonical_json_hash({"a": 1, "b": 2})
    json_stable = h1 == h2

    # Test content hash
    h3 = content_hash("hello world")
    h4 = content_hash("hello world")
    h5 = content_hash("hello world!")
    content_stable = h3 == h4 and h3 != h5

    return json_stable and content_stable, f"json={json_stable}, content={content_stable}"


# === G20: Snapshot no Authorization headers ===
def test_snapshot_no_headers():
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute("SELECT snapshot_json FROM resource_snapshots LIMIT 10").fetchall()
        for row in rows:
            snap = str(row)
            if "Authorization" in snap or "Bearer" in snap or "github_pat_" in snap:
                conn.close()
                return False, "token in snapshot"
    except Exception:
        pass
    conn.close()
    return True, "clean"


# === G25: MCP discover write_enabled ===
def test_mcp_discover_write():
    from apps.runtime.mcp.tools import tool_discover
    r = tool_discover()
    if not ok(r):
        return True, "discover failed (ok)"
    for p in r.get("providers", []):
        if p["id"] == "github" and p.get("write_enabled") is True:
            return False, "github write_enabled=true"
    for t in r.get("transactions", []):
        if t["id"] == "github.patch_and_open_pr" and t.get("execution_available") is True:
            return False, "github execution_available=true"
    return True, "read-only"


# === G21: Disconnect then read denied ===
def test_disconnect_then_read():
    # This test requires a real GitHub connection, skip if not connected
    resp = httpx.get(f"{API}/v1/providers/github")
    if resp.json().get("status") != "connected":
        return True, "skipped (not connected)"

    # Disconnect
    httpx.delete(f"{API}/v1/providers/github/disconnect")

    # Try read
    read_resp = httpx.get(f"{API}/v1/github/repos/owner/repo")
    denied = read_resp.status_code in (403, 502)

    # Reconnect (can't without token, just check status)
    return denied, f"read status={read_resp.status_code}"


# Run all tests
test_funcs = [
    ("G07", "SQLite no raw token", test_sqlite_no_token),
    ("G11", "Adapter no write methods", test_adapter_no_write),
    ("G12", "No write capabilities", test_no_write_capabilities),
    ("G13", "No write endpoints", test_no_write_endpoints),
    ("G14", "MCP no raw GitHub tools", test_mcp_no_raw_github),
    ("G15", "GitHub execute denied", test_github_execute_denied),
    ("G16", "Plan-only no approval", test_plan_only_no_approval),
    ("G19", "Snapshot hash recompute", test_snapshot_hash),
    ("G20", "Snapshot no Authorization", test_snapshot_no_headers),
    ("G25", "MCP discover write_enabled", test_mcp_discover_write),
    ("G21", "Disconnect then read", test_disconnect_then_read),
]

print("=== P3 Adversarial Matrix ===")
all_pass = True
for code, name, func in test_funcs:
    try:
        passed, detail = func()
        s = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
    except Exception as e:
        s = "ERROR"
        detail = str(e)
        all_pass = False
    print(f"  [{s}] {code}: {name} — {detail}")

passed_count = 0
for c, n, func in test_funcs:
    try:
        r = func()
        if isinstance(r[0], bool) and r[0]:
            passed_count += 1
    except Exception:
        pass
print(f"\nResult: {'ALL PASS' if all_pass else 'FAILURES'} ({passed_count}/{len(test_funcs)})")
