# WebFA Desktop 版本路线与冻结约束

## 已完成阶段

### v0.1.5 — Phase 1: Runtime Core (冻结)

Tag: `v0.1.5-phase1-runtime-core`
Tests: 73 passed, 评分 100/100

交付物:
- Mock transaction 完整闭环: plan → preview → approval → execute → verify → proof → audit
- PlanService + plan_hash (canonical JSON + sha256)
- PolicyEngine (blocked path / file count / diff size / risk)
- ApprovalService (token 生成 / hash-only 存储 / 过期)
- ExecutionService (状态机 / 幂等性)
- VerificationService (4 项检查)
- ProofService (DB + 文件)
- AuditService (事件链 / redaction)
- MockProvider
- REST API: 14 endpoints
- Console UI: mock transaction 操作

冻结约束:
- plan_hash 篡改检测必须通过 (P0-6 regression test)
- 未 approval 不能 execute
- rejected approval 不能 execute
- token 只返回一次

---

### v0.2.0 — Phase 2: MCP stdio (冻结)

Tag: `v0.2.0-mcp-stdio`
Tests: 99 passed, 评分 100/100

交付物:
- MCP stdio server (FastMCP)
- 6 MCP tools: discover / plan / preview / execute / get_execution / get_proof
- Runtime Client (HTTP → Runtime REST API)
- Error mapping (403→approval_required, 409→hash_mismatch)
- Config generator
- Electron MCP Process Manager
- Console MCP status + config UI

冻结约束:
- MCP 只是协议适配层，不写 DB
- MCP 不暴露 approve/reject/admin tools
- MCP 不泄露 token/credential
- Runtime stopped 时 MCP 返回 runtime_unavailable

---

### v0.3.0 — Phase 3: GitHub Read Context (冻结)

Tag: `v0.3.0-github-read-context`
Tests: 114 passed, 评分 100/100

交付物:
- GitHub credential store (文件级 token 存储)
- GitHub read-only adapter (repo/branch/tree/file/issue/comments)
- Provider connection API (connect/test/disconnect)
- Resource snapshots (content_hash + taint_level)
- GitHub workspace import
- Plan-only readiness for github.patch_and_open_pr
- Console GitHub connection UI
- MCP discover: GitHub read_only / write_enabled=false

冻结约束:
- token 只存在 credential store，不进入 SQLite/logs/audit/snapshot
- GitHub adapter 无 write methods
- github.patch_and_open_pr 只能 plan-only，不能 execute
- plan-only preview 不创建 approval
- 所有 GitHub 外部内容标记 taint_level

---

## 待完成阶段

### v0.4.0 — Phase 4: GitHub PR Transaction (待做)

目标: 跑通 github.patch_and_open_pr 真实写操作

交付物:
- GitHub write adapter (branch/commit/PR)
- Diff generation (基于真实文件)
- Blocked path check (基于真实 tree)
- Approval diff preview (真实 diff)
- Verification (回读 PR/commit/changed files)
- Proof bundle (真实 resource proof)
- Audit timeline

关键约束:
- 只创建 draft PR，不 merge
- 不删除 branch
- 不修改 workflow/secret/env/key
- 不修改无权限仓库
- 公开 repo 默认 plan-only

---

### v0.5.0 — Phase 5: HF Connection (待做)

目标: WebFA 能连接 Hugging Face 并读取模型信息

交付物:
- HF token 配置页面
- HF credential store
- model search / read / card read
- target repo read

---

### v0.6.0 — Phase 6: HF Transaction (待做)

目标: 跑通 hf.compare_and_publish

交付物:
- model profile extraction
- comparison report generation
- source trace
- README generation
- approval preview
- README update
- revision verify
- content hash proof

---

### v0.7.0 — Phase 7: 打包发布 (待做)

目标: 生成可安装桌面应用

交付物:
- Windows installer
- runtime binary (PyInstaller/Nuitka)
- auto port detection
- log export
- diagnostic page
- first-run onboarding

---

## 不做的事情 (冻结)

以下内容在 v0.x 系列中不做:

- SaaS 版本
- 浏览器自动化
- 批量 PR/issue/comment
- 自动 merge PR
- 删除资源
- 成员管理/权限管理/组织设置
- Agent 直接拿 token
- Agent 绕过用户审批执行高风险写操作
- 默认修改 workflow/secret/env/key 文件
- OAuth
- GitHub App (v1 再考虑)
- MCP HTTP/SSE (v0 只做 stdio)
