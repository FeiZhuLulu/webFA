# WebFA Desktop

WebFA Desktop 是一个本地运行的 **Agent Action Transaction Gateway**。它不是浏览器自动化工具，不是 API wrapper，而是给 Agent 使用的在线平台事务运行时。

## 当前状态

```text
v0.1.5  Phase 1: Runtime Core           ✅ 冻结  73 tests  100/100
v0.2.0  Phase 2: MCP stdio              ✅ 冻结  99 tests  100/100
v0.3.0  Phase 3: GitHub Read Context    ✅ 冻结  114 tests 100/100
v0.4.0  Phase 4: GitHub PR Transaction  待做
v0.5.0  Phase 5: HF Connection          待做
v0.6.0  Phase 6: HF Transaction         待做
v0.7.0  Phase 7: 打包发布                待做
```

## 已完成

### Runtime Core (Phase 1)

- Mock transaction 完整闭环: plan → preview → approval → execute → verify → proof → audit
- PlanService + plan_hash (canonical JSON + sha256)
- PolicyEngine (blocked path / file count / diff size / risk)
- ApprovalService (token 生成 / hash-only 存储 / 过期)
- ExecutionService (状态机 / 幂等性)
- VerificationService / ProofService / AuditService
- MockProvider
- 14 REST API endpoints
- Console UI

### MCP stdio (Phase 2)

- MCP stdio server (FastMCP)
- 6 MCP tools: discover / plan / preview / execute / get_execution / get_proof
- Runtime Client (HTTP → Runtime REST API)
- Error mapping / Config generator
- Electron MCP Process Manager
- Console MCP status + config UI

### GitHub Read Context (Phase 3)

- GitHub credential store (文件级 token 存储)
- GitHub read-only adapter (repo / branch / tree / file / issue / comments)
- Provider connection API (connect / test / disconnect)
- Resource snapshots (content_hash + taint_level)
- GitHub workspace import
- Plan-only readiness for github.patch_and_open_pr
- Console GitHub connection UI

## 未完成

- 真实 GitHub 写操作 (create branch / commit / PR)
- Hugging Face 连接与读取
- hf.compare_and_publish 真实执行
- Codex plugin 集成
- Windows installer / macOS app
- OAuth / GitHub App
- MCP HTTP / SSE

## 架构

```text
Agent → MCP stdio → WebFA Runtime → GitHub / Hugging Face
                       ↓
              preview → approval → execute → verify → proof → audit
```

```text
webfa/
  apps/
    desktop/
      electron/          # Electron shell: window, tray, process manager
      renderer/          # Next.js console UI
    runtime/
      api/routes/        # REST API endpoints
      mcp/               # MCP stdio server + tools + client
      main.py            # FastAPI app

  packages/
    webfa-core/          # Business logic
      registry/          # Transaction + capability registry
      planner/           # PlanService + plan_hash
      policy/            # PolicyEngine
      approvals/         # ApprovalService
      execution/         # ExecutionService + state machine
      verification/      # VerificationService
      proof/             # ProofService
      audit/             # AuditService
      workspace/         # WorkspaceStore

    providers/
      mock/              # Mock adapter
      github/            # GitHub read-only adapter

    schemas/             # Pydantic v2 contracts
    storage/             # SQLite + models + credential store

  resources/
    transactions/        # YAML transaction definitions
    capabilities/        # YAML capability definitions
    policies/            # YAML policy definitions

  docs/
    reports/             # Adversarial acceptance reports
    security/            # Security invariants + credential handling
    roadmap/             # Version roadmap + frozen constraints

  tests/
    unit/
    integration/
    contract/
```

## Quick start

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e '.[dev]'

# Run runtime
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787

# Run MCP server
python -m apps.runtime.mcp.server

# Run tests
pytest

# Typecheck
npx tsc -p apps/desktop/renderer/tsconfig.json --noEmit
npx tsc -p apps/desktop/electron/tsconfig.json --noEmit
```

## REST API

```text
GET  /health
GET  /v1/providers
GET  /v1/transactions

POST /v1/plans
GET  /v1/plans/{plan_id}
POST /v1/plans/{plan_id}/preview

GET  /v1/approvals
GET  /v1/approvals/{approval_id}
POST /v1/approvals/{approval_id}/approve
POST /v1/approvals/{approval_id}/reject

POST /v1/executions
GET  /v1/executions/{execution_id}

GET  /v1/proofs/{proof_id}
GET  /v1/audits

POST /v1/providers/github/connect
POST /v1/providers/github/test
DELETE /v1/providers/github/disconnect
GET  /v1/providers/github

GET  /v1/github/repos/{owner}/{repo}
GET  /v1/github/repos/{owner}/{repo}/branches/{branch}
GET  /v1/github/repos/{owner}/{repo}/tree
GET  /v1/github/repos/{owner}/{repo}/files
GET  /v1/github/repos/{owner}/{repo}/issues/{issue_number}
GET  /v1/github/repos/{owner}/{repo}/issues/{issue_number}/comments
GET  /v1/github/rate_limit

POST /v1/github/workspaces/import

GET  /v1/mcp/config
GET  /v1/mcp/status
```

## MCP Tools

```text
webfa.discover        # 发现 provider / transaction
webfa.plan            # 创建 plan
webfa.preview         # 生成 diff + approval
webfa.execute         # 执行已批准 plan
webfa.get_execution   # 查询执行状态
webfa.get_proof       # 查询 proof
```

## 安全规则

- Agent 永远不能接触 token
- token 只存 credential store，不进入 SQLite / logs / audit / snapshot
- Approval 绑定 plan_hash 和 diff_hash
- Blocked paths 后端强制阻断
- 外部内容标记 taint_level
- 未批准不能 execute
- GitHub 在 P3 只读，写操作保留到 P4
- MCP 只是协议适配层，不写 DB

## 测试

```text
114 passed
- 12 contract tests
- 24 integration tests
- 78 unit tests
```

## 文档

- [Phase 1 验收报告](docs/reports/phase1-adversarial-acceptance.md)
- [Phase 2 验收报告](docs/reports/p2-mcp-adversarial-acceptance.md)
- [Phase 3 验收报告](docs/reports/p3-github-read-context-adversarial-acceptance.md)
- [安全不变量](docs/security/invariants.md)
- [GitHub 凭证处理](docs/security/github-credential-handling.md)
- [版本路线](docs/roadmap/stage-roadmap-and-frozen-constraints.md)
