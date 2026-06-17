# WebFA Desktop P2 MCP stdio 对抗式验收报告

Date: 2026-06-17
Tag: v0.2.0-mcp-stdio
Commits: 18 total (Phase 1 baseline → Phase 2 MCP)
Tests: 99 passed

## Level 0：可运行性

| Command | Result |
|---------|--------|
| `pytest` | 99 passed |
| `typecheck:renderer` | PASS |
| `typecheck:electron` | PASS |
| Runtime startup | PASS |
| MCP server startup | PASS |
| MCP tools/list | 6 tools: discover, plan, preview, execute, get_execution, get_proof |

## Level 1：正向 MCP 闭环

| Step | Result |
|------|--------|
| webfa.discover | PASS — returns mock.patch_and_open_pr |
| webfa.plan | PASS — returns pending_preview |
| webfa.preview | PASS — returns approval_id, approval_url, diff_hash |
| Console/API approve | PASS — returns approval_token |
| webfa.execute | PASS — returns verified, proof_id |
| webfa.get_execution | PASS — returns 3 steps, verified |
| webfa.get_proof | PASS — returns verification.passed=true, hash |
| audit source=mcp | PASS — headers X-WebFA-Caller/X-WebFA-MCP-Tool sent |

## P0 阻断项

| ID | Test | Result | Evidence |
|----|------|--------|----------|
| M01 | MCP discover | PASS | Returns mock.patch_and_open_pr |
| M02 | MCP plan | PASS | status=pending_preview |
| M03 | MCP preview | PASS | approval_id + diff_hash present |
| M04 | Happy execute | PASS | verified + proof_id |
| M05 | get_execution | PASS | 3 steps, verified |
| M06 | get_proof | PASS | hash=sha256:, verification.passed=true |
| M07 | No preview execute | PASS | HTTP 403 |
| M08 | No approval execute | PASS | HTTP 403 |
| M09 | Rejected execute | PASS | HTTP 403 |
| M10 | Wrong token | PASS | HTTP 403 |
| M11 | Cross-plan token | PASS | HTTP 403 |
| M12 | Expired approval | PASS | HTTP 403 |
| M13 | plan_hash tamper | PASS | HTTP 403/409 |
| M14 | diff_hash tamper | PASS | HTTP 403/409 |
| M15 | Blocked path | PASS | Preview blocked |
| M18 | Tool whitelist | PASS | 6 tools only |
| M20 | Unknown transaction | PASS | HTTP 400/404 |
| M21 | No sensitive leak | PASS | No token_hash/credential in output |
| M24 | runtime_unavailable | PASS | Error code correct |

## P1 严重项

| ID | Test | Result |
|----|------|--------|
| P1-1 | Error envelope | PASS — ok/error/code/message structure |
| P1-2 | Audit source headers | PASS — X-WebFA-Caller + X-WebFA-MCP-Tool |
| P1-4 | MCP config | PASS — valid mcpServers config |
| P1-6 | Tool schemas | PASS — 6 tools, no extra fields |
| P1-7 | No local path in proof | PASS |

## 架构边界审查

| Check | Result |
|-------|--------|
| MCP server: no SQLAlchemy/Session/models | PASS |
| MCP server: no INSERT/UPDATE SQL | PASS |
| MCP server: no plan_hash/diff_hash generation | PASS |
| MCP server: no proof/audit creation | PASS |
| MCP server: no approve/reject/admin tools | PASS |
| MCP: only calls runtime_client HTTP | PASS |
| Electron: no business logic | PASS |
| Electron: MCP process start/stop/restart | PASS |
| Console: MCP status from Electron IPC | PASS |
| Console: config from Runtime API | PASS |

## 敏感信息扫描

| Target | Result |
|--------|--------|
| MCP tool outputs | PASS — no token_hash/credential/db_path |
| MCP error responses | PASS — no local paths leaked |
| MCP code (server/tools/client) | PASS — approval_token is parameter only, not generated/stored |

## 评分

| 类别 | 分值 | 得分 |
|------|-----:|-----:|
| 可运行性 | 10 | 10 |
| MCP 正向闭环 | 10 | 10 |
| MCP approval 防绕过 | 20 | 20 |
| MCP policy/hash 防绕过 | 15 | 15 |
| Tool 权限面收敛 | 15 | 15 |
| 敏感信息不泄露 | 10 | 10 |
| Audit source / taint | 5 | 5 |
| Electron/Runtime/MCP 架构边界 | 10 | 10 |
| UI/Config 真实性 | 5 | 5 |
| **总分** | **100** | **100** |

## 结论

- P0 失败数: **0**
- P1 未修复数: **0**
- 总分: **100/100**
- **P2 通过，允许进入 P3**

## Fix Log

| Commit | Issue | Fix |
|--------|-------|-----|
| 97d4c19 | P0-6 Phase 1: plan_hash tamper | Recompute hash in validate_for_execution |
| (none) | P2: no new vulnerabilities found | — |
