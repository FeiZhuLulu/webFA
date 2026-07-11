# P11.10 Step-up UI, Audit & Final Acceptance Report

Status: complete

## Scope

P11.10 completes the WebFA Agent Safety Contract without turning WebFA into a second intelligent approval Agent.

The completed path is:

```text
Agent task declaration and assertions
  -> deterministic Runtime evidence
  -> Profile / resource / financial hard-boundary evaluation
  -> allow_with_audit, assertion, takeover, deny, or exact-scope step-up
  -> semantic WebOperation
  -> secret-free SafetyReceipt
```

The default trusted-Agent path remains autonomous. Step-up is used only when an actual configured boundary is exceeded.

## Exact-scope step-up

Added a session-local `StepUpManager` and typed schemas:

- `StepUpRequest`;
- `StepUpRequestState`;
- `StepUpReason`;
- `StepUpStatus`;
- `SafetyOperationEnvelope.step_up_id`.

A step-up request is bound to:

```text
Agent ID
Profile ID
Origin
WebObject target
semantic operation
SafetyContext, when present
exact requested scope
expiry
single use
```

It is not a general approval token. A grant approved for one amount, currency, target, operation, Origin, Agent, or Profile cannot be reused for another.

Supported initial escalation reasons:

```text
financial_limit
financial_assurance
identity_switch
profile_scope
unknown_external_effect
policy_escalation
```

Lifecycle:

```text
pending
  -> approved
  -> consumed

pending
  -> rejected

pending / approved
  -> expired
```

Approved grants are consumed only after the semantic operation actually executes.

## Financial step-up flow

The real Managed Chromium regression validates:

```text
Runtime-observed order total: CNY 279.00
Financial autonomy limit: CNY 100.00
Step-up limit: CNY 500.00
```

Initial operation:

```text
provide_payment_instrument
  -> require_step_up
  -> executed=false
  -> pending step_up_id
  -> not_executed SafetyReceipt
```

The user approves the exact request through the Visualizer API or Safety Center. The Agent retries the same operation with:

```text
context_id + step_up_id
```

WebFA verifies the complete binding and amount/currency scope, executes the operation once, consumes the grant, updates financial usage, and emits an executed SafetyReceipt.

## Profile step-up

User-owned Profile identity changes such as `switch_account` generate scoped requests rather than a generic confirmation prompt. The same manager supports future Profile and unknown-effect escalation without adding a new MCP tool.

## Visualizer Safety Center

Added a Safety Center panel that exposes:

- pending and approved step-up requests;
- exact current and requested scopes;
- approve-once and reject controls;
- Profile ownership, trust mode, Origin, and unknown-effect policy;
- FinancialPolicy registration and binding;
- safe PaymentInstrumentRef registration and revocation;
- recent SafetyReceipt history.

The UI is a local policy and boundary-escalation surface. It is not a constant approval queue.

## Safety receipts

Added a bounded session-local `SafetyReceiptStore`.

Every operation that reaches a P11 safety decision produces a receipt, including:

```text
allow_with_audit
require_assertion
require_step_up
require_takeover
deny
```

Receipts record:

- Agent and Profile;
- Origin and target WebObject;
- semantic operation and P10 effect;
- active safety dimensions;
- assertion references;
- hard-boundary and final decision;
- document revisions;
- authority source reference;
- step-up reference;
- executed, not-executed, takeover, denied, or failed result;
- timestamp.

Receipts do not contain:

- passwords;
- cookies or authentication tokens;
- OTP/2FA values;
- full card numbers;
- CVV/CVC;
- payment passwords;
- wallet tokens;
- local absolute paths.

Visualizer endpoints:

```text
GET  /v1/visualizer/step-ups
POST /v1/visualizer/step-ups/{id}/approve
POST /v1/visualizer/step-ups/{id}/reject
GET  /v1/visualizer/safety-receipts
GET  /v1/visualizer/safety-receipts/{id}
```

These endpoints are human-facing Visualizer controls. They do not add Agent-facing MCP tools.

## Public Agent surface

The default MCP surface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

The Agent retries a step-up operation through the existing `webfa.act` safety envelope. No `webfa.approve`, `webfa.pay`, or `webfa.authorize` tool was added.

## Validation

Automated coverage includes:

- strict step-up schema and lifecycle;
- exact binding validation;
- exact scope validation;
- single-use consumption;
- reject and expiry behavior;
- bounded receipt storage;
- secret-free receipt contract;
- Visualizer approve/reject endpoints;
- real Managed Chromium financial step-up flow;
- MCP tool count and schema regression;
- P10 WebObject and semantic-operation regression.

Final acceptance commands:

```text
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
git diff --check
```

Final result at P11.10 completion:

```text
Python tests:        397 passed
Renderer typecheck:  passed
Electron typecheck:  passed
Python build:        passed
Diff check:          passed
```

Only the existing upstream `websockets` / `uvicorn` deprecation warnings remain.

## P11 final acceptance

P11.0-P11.10 now satisfy the frozen product model:

1. WebFA has no LLM and does not interpret user conversations.
2. Safety templates are site-independent and composable.
3. Trusted Agents may proceed without duplicate WebFA confirmation when assertions and hard boundaries are satisfied.
4. Agent-owned unknown external effects default to `allow_with_audit` when declared.
5. Password, 2FA, CAPTCHA, biometric, and payment verification remain Human Takeover.
6. Local upload uses opaque scoped resource references.
7. Payment instruments expose safe references and metadata only.
8. Financial limits are user-defined and mechanically enforced.
9. Boundary escalation is exact-scope, expiring, and single-use.
10. Safety decisions produce secret-free receipts.
11. No site-specific operation allowlist is required.
12. The default Agent MCP surface remains five tools.

## Remaining boundaries

P11 state is session-local:

- Profile policy metadata;
- resource grants;
- financial policies and usage;
- payment instrument references;
- step-up requests;
- SafetyReceipts.

Durable restoration and resumable traces belong to P13. Multiple isolated Chromium Profiles and concurrent sessions belong to P12. Raw-card Vault support remains disabled and requires a separate security review.
