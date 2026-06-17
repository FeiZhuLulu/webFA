"""P2 Adversarial Test Script — runs MCP tools against live Runtime."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from apps.runtime.mcp.tools import (
    tool_discover,
    tool_execute,
    tool_get_execution,
    tool_get_proof,
    tool_plan,
    tool_preview,
)

API = "http://127.0.0.1:8787"
DB = os.path.join(os.environ["APPDATA"], "WebFA", "webfa.db")
results = []


def ok(r):
    return r.get("ok", False)


def err_code(r):
    return r.get("error", {}).get("code", "")


def err_status(r):
    return r.get("error", {}).get("runtime_status", 0)


def approve_via_api(approval_id):
    resp = httpx.post(f"{API}/v1/approvals/{approval_id}/approve")
    return resp.json().get("approval_token", "")


def reject_via_api(approval_id):
    httpx.post(f"{API}/v1/approvals/{approval_id}/reject")


def tamper_plan(plan_id, field, value):
    conn = sqlite3.connect(DB)
    conn.execute(f"UPDATE plans SET {field} = ? WHERE id = ?", (value, plan_id))
    conn.commit()
    conn.close()


def tamper_approval(approval_id, field, value):
    conn = sqlite3.connect(DB)
    conn.execute(f"UPDATE approvals SET {field} = ? WHERE id = ?", (value, approval_id))
    conn.commit()
    conn.close()


# === M01: discover ===
r = tool_discover()
pass_ = ok(r) and any(t["id"] == "mock.patch_and_open_pr" for t in r.get("transactions", []))
results.append(("M01", "discover", pass_))

# === M02: plan ===
r = tool_plan("mock.patch_and_open_pr", {"owner": "t", "repo": "t", "issue_number": 1, "task_description": "Test"})
pass_ = ok(r) and r.get("status") == "pending_preview"
P1 = r.get("plan_id") if pass_ else None
results.append(("M02", "plan", pass_))

# === M03: preview ===
r = tool_preview(P1)
pass_ = ok(r) and r.get("approval_id") is not None and r.get("diff_hash") is not None
A1 = r.get("approval_id") if pass_ else None
results.append(("M03", "preview", pass_))

# === M07: execute without preview ===
r_plan = tool_plan("mock.patch_and_open_pr", {"owner": "t", "repo": "t", "issue_number": 7, "task_description": "No preview"})
P_no_prev = r_plan.get("plan_id")
r = tool_execute(P_no_prev, "fake")
pass_ = not ok(r) and err_status(r) == 403
results.append(("M07", "no preview execute", pass_))

# === M08: execute without approval ===
r_plan2 = tool_plan("mock.patch_and_open_pr", {"owner": "t", "repo": "t", "issue_number": 8, "task_description": "No approve"})
P_no_appr = r_plan2.get("plan_id")
tool_preview(P_no_appr)
r = tool_execute(P_no_appr, "fake")
pass_ = not ok(r) and err_status(r) == 403
results.append(("M08", "no approval execute", pass_))

# === M09: rejected approval execute ===
r_plan3 = tool_plan("mock.patch_and_open_pr", {"owner": "t", "repo": "t", "issue_number": 9, "task_description": "Reject"})
P_rej = r_plan3.get("plan_id")
r_prev3 = tool_preview(P_rej)
A_rej = r_prev3.get("approval_id")
reject_via_api(A_rej)
r = tool_execute(P_rej, "fake")
pass_ = not ok(r) and err_status(r) == 403
results.append(("M09", "rejected execute", pass_))

# === M10: wrong token ===
# Need a fresh approved plan
r_fresh = tool_plan("mock.patch_and_open_pr", {"owner": "f", "repo": "f", "issue_number": 10, "task_description": "Fresh"})
P_fresh = r_fresh.get("plan_id")
r_prev_f = tool_preview(P_fresh)
A_fresh = r_prev_f.get("approval_id")
approve_via_api(A_fresh)

r = tool_execute(P_fresh, "wrong_token_abc123")
pass_ = not ok(r) and err_status(r) == 403
results.append(("M10", "wrong token", pass_))

# === M11: cross-plan token ===
r_B = tool_plan("mock.patch_and_open_pr", {"owner": "b", "repo": "b", "issue_number": 11, "task_description": "Plan B"})
P_B = r_B.get("plan_id")
tool_preview(P_B)

# Get token from plan A (A1)
token_A = approve_via_api(A1)
r = tool_execute(P_B, token_A)
pass_ = not ok(r) and err_status(r) == 403
results.append(("M11", "cross-plan token", pass_))

# === M12: expired approval ===
r_e = tool_plan("mock.patch_and_open_pr", {"owner": "exp", "repo": "exp", "issue_number": 12, "task_description": "Expiry"})
P_exp = r_e.get("plan_id")
r_prev_exp = tool_preview(P_exp)
A_exp = r_prev_exp.get("approval_id")
token_exp = approve_via_api(A_exp)
tamper_approval(A_exp, "expires_at", "2020-01-01 00:00:00")
r = tool_execute(P_exp, token_exp)
pass_ = not ok(r) and err_status(r) == 403
results.append(("M12", "expired approval", pass_))

# === M13: plan_hash tamper ===
r_t = tool_plan("mock.patch_and_open_pr", {"owner": "tamper", "repo": "tamper", "issue_number": 13, "task_description": "Tamper"})
P_tamper = r_t.get("plan_id")
r_prev_t = tool_preview(P_tamper)
A_tamper = r_prev_t.get("approval_id")
token_tamper = approve_via_api(A_tamper)
tamper_plan(P_tamper, "input_json", '{"owner":"attacker","repo":"evil"}')
r = tool_execute(P_tamper, token_tamper)
pass_ = not ok(r) and err_status(r) in (403, 409)
results.append(("M13", "plan_hash tamper", pass_))

# === M14: diff_hash tamper ===
r_d = tool_plan("mock.patch_and_open_pr", {"owner": "diff", "repo": "diff", "issue_number": 14, "task_description": "Diff tamper"})
P_diff = r_d.get("plan_id")
r_prev_d = tool_preview(P_diff)
A_diff = r_prev_d.get("approval_id")
token_diff = approve_via_api(A_diff)
conn = sqlite3.connect(DB)
conn.execute("UPDATE plans SET target_json = json_set(target_json, '$.diff_hash', 'sha256:tampered') WHERE id = ?", (P_diff,))
conn.commit()
conn.close()
r = tool_execute(P_diff, token_diff)
pass_ = not ok(r) and err_status(r) in (403, 409)
results.append(("M14", "diff_hash tamper", pass_))

# === M15: blocked path ===
r_bp = tool_plan("mock.patch_and_open_pr", {"owner": "bp", "repo": "bp", "issue_number": 15, "task_description": "Blocked", "blocked_paths": ["src/**"]})
P_bp = r_bp.get("plan_id")
r = tool_preview(P_bp)
pass_ = not ok(r)
results.append(("M15", "blocked path", pass_))

# === M20: unknown transaction ===
r = tool_plan("evil.force_execute", {})
pass_ = not ok(r) and err_status(r) in (400, 404)
results.append(("M20", "unknown transaction", pass_))

# === M21: sensitive info leak ===
leak_checks = []
r_disc = tool_discover()
disc_str = json.dumps(r_disc)
r_prev_check = tool_preview(P_fresh)
prev_str = json.dumps(r_prev_check)
r_proof = tool_get_proof(r_fresh.get("proof_id", "nonexistent") if not ok(r_fresh) else PR1 if "PR1" in dir() else "x")
proof_str = json.dumps(r_proof)

for sensitive in ["approval_token_hash", "credential_ref", "db_path", "proof_file_path", "C:\\Users"]:
    if sensitive in disc_str or sensitive in prev_str:
        leak_checks.append(sensitive)
pass_ = len(leak_checks) == 0
results.append(("M21", "no sensitive leak", pass_))

# === M24: Runtime stopped test (simulated) ===
# Can't actually stop Runtime from here, but verify error mapping works
from apps.runtime.mcp.runtime_client import RuntimeUnavailableError
from apps.runtime.mcp.errors import map_unavailable_error
r = map_unavailable_error(RuntimeUnavailableError("Runtime unreachable"))
pass_ = r.get("error", {}).get("code") == "runtime_unavailable"
results.append(("M24", "runtime_unavailable mapping", pass_))

# Print results
print("=== P2 MCP Adversarial Matrix ===")
all_pass = True
for code, name, passed in results:
    s = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{s}] {code}: {name}")

print(f"\nResult: {'ALL PASS' if all_pass else 'FAILURES'} ({sum(1 for _, _, p in results if p)}/{len(results)})")
