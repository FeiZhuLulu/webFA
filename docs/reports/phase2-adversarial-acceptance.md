# Phase 2 MCP Adversarial Acceptance Report

Date: 2026-06-17
Branch: master
Tag: v0.2.0-mcp-stdio
Tests: 99 passed

## Level 0: Runnable

| Command | Result |
|---------|--------|
| `pytest` | 99 passed |
| `typecheck:renderer` | PASS |
| `typecheck:electron` | PASS |
| Runtime startup | PASS |
| MCP server startup | PASS |

## MCP Adversarial Matrix

| ID | Test | Result |
|----|------|--------|
| M01 | MCP discover returns mock.patch_and_open_pr | PASS |
| M02 | MCP plan creates pending_preview plan | PASS |
| M03 | MCP preview creates approval + approval_url | PASS |
| M04 | MCP execute without approval → 403 | PASS |
| M05 | MCP execute wrong token → 403 | PASS |
| M06 | MCP execute with valid token → verified | PASS |
| M07 | MCP get_execution returns verified | PASS |
| M08 | MCP get_proof returns proof with hash | PASS |
| M09 | Audit events recorded | PASS |
| M10 | No token_hash in MCP responses | PASS |
| M11 | Cross-plan token reuse → 403 | PASS |
| M12 | Plan hash tamper via SQLite → 403/409 | PASS |
| M13 | Blocked path (src/**) → preview blocked | PASS |
| M14 | Expired approval → 403 | PASS |
| M15 | No business logic in mcpProcess.ts | PASS |
| M16 | No approve/admin MCP tools | PASS |
| M17 | No business logic in Electron main | PASS |

## Verdict

**PASS** — Phase 2 MCP stdio accepted. 0 failures across 17 adversarial tests.

## Security Invariants Verified

- MCP is protocol adapter only (no DB writes, no hash generation)
- MCP execute delegates to Runtime approval validation
- MCP cannot bypass preview/approval/policy
- MCP does not expose token_hash, credentials, or local paths
- MCP tools limited to: discover, plan, preview, execute, get_execution, get_proof
- Electron MCP manager has no business logic
