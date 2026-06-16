# WebFA Desktop v0.1.5 — Phase 1: Core Runtime

WebFA Desktop is a local Agent Action Transaction Gateway. This branch implements **Phase 1**: the core transaction runtime with mock transaction closure.

## What's new in Phase 1

Phase 0 skeleton → Phase 1 runtime core:

- **Mock transaction**: `mock.patch_and_open_pr` — full closure without external API calls
- **Plan Service**: create plans, compute plan_hash (canonical JSON + sha256)
- **Policy Engine**: blocked paths, file count, diff size, risk checks
- **Preview**: generates mock diff, diff_hash, policy check, creates approval
- **Approval Service**: approve/reject, token generation (hash-only stored in DB), expiry
- **Execution Service**: validates approval, runs mock steps (branch/commit/PR), state machine
- **Mock Provider**: simulates GitHub-like operations without network calls
- **Verification Service**: verifies mock resources (branch, commit, PR, diff_hash)
- **Proof Service**: generates proof bundle (DB + file), proof_hash
- **Audit Service**: full event chain, sensitive field redaction
- **REST API**: all Phase 1 endpoints
- **Console UI**: Create Mock Transaction, pending approvals, approve/reject, execution display
- **72 tests**: unit, integration, contract, full flow

## REST API

```text
GET  /health
GET  /v1/providers
GET  /v1/transactions

POST /v1/plans                          # Create plan
GET  /v1/plans/{plan_id}                # Get plan
POST /v1/plans/{plan_id}/preview        # Preview + policy check + create approval

GET  /v1/approvals                      # List approvals
GET  /v1/approvals/{approval_id}        # Get approval
POST /v1/approvals/{approval_id}/approve  # Approve
POST /v1/approvals/{approval_id}/reject   # Reject

POST /v1/executions                     # Execute (requires approval token)
GET  /v1/executions/{execution_id}      # Get execution

GET  /v1/proofs/{proof_id}              # Get proof
GET  /v1/audits                         # List audit events
```

## Quick start

```bash
cd webfa
python -m venv .venv
source .venv/Scripts/activate
pip install -e '.[dev]'

# Run runtime
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787 --reload

# Run tests
pytest

# Typecheck
npx tsc -p apps/desktop/renderer/tsconfig.json --noEmit
npx tsc -p apps/desktop/electron/tsconfig.json --noEmit
```

## Mock transaction demo

```bash
# 1. Create plan
curl -X POST http://127.0.0.1:8787/v1/plans \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"mock.patch_and_open_pr","input":{"owner":"mock-owner","repo":"mock-repo","issue_number":1,"task_description":"Fix mock issue."}}'

# 2. Preview (use plan_id from step 1)
curl -X POST http://127.0.0.1:8787/v1/plans/{plan_id}/preview

# 3. Approve (use approval_id from step 2)
curl -X POST http://127.0.0.1:8787/v1/approvals/{approval_id}/approve

# 4. Execute (use plan_id and approval_token from steps 1 and 3)
curl -X POST http://127.0.0.1:8787/v1/executions \
  -H 'Content-Type: application/json' \
  -d '{"plan_id":"{plan_id}","approval_token":"{approval_token}"}'

# 5. Get proof (use proof_id from step 4)
curl http://127.0.0.1:8787/v1/proofs/{proof_id}

# 6. Get audit trail
curl http://127.0.0.1:8787/v1/audits?workspace_id={workspace_id}
```

## Execution flow

```text
plan.created → plan.previewed → policy.checked → approval.created
  → approval.approved → execution.created → execution.started
  → execution.step.started → execution.step.succeeded (×3)
  → execution.verifying → proof.created → execution.verified
```

## Security rules enforced

- Agent cannot read tokens
- Tokens stored as sha256 hash only
- Approval binds plan_hash and diff_hash
- Blocked paths are enforced
- External content marked tainted
- Unapproved execution returns 403
- Idempotency key prevents duplicate executions
- Sensitive fields redacted in audit payloads

## Test summary

```text
72 passed
- 3 contract tests
- 16 integration tests
- 53 unit tests
```

## Deliberately excluded from Phase 1

- Real GitHub API
- Real Hugging Face API
- MCP stdio server
- OAuth / token storage
- Installer packaging
- Business logic in Electron
