# P11 Final Acceptance Report

Status: complete

Phase:

```text
P11 Agent Safety Contract & Hard Boundaries
```

## Outcome

P11 is complete from P11.0 through P11.10.

WebFA now provides a complete, LLM-free safety contract for real web tasks:

```text
Agent interprets user intent
  -> SafetyDeclaration
  -> versioned SafetyContract
  -> AgentAssertions
  -> Runtime evidence elevation
  -> deterministic hard-boundary checks
  -> semantic WebOperation
  -> optional exact-scope step-up
  -> secret-free SafetyReceipt
```

The normal trusted-Agent path remains `allow_with_audit`. WebFA does not repeat user approval when the Agent already has explicit authority and the operation remains inside configured boundaries.

## Completed model

P11 implements:

- eight composable safety dimensions;
- task-scoped SafetyContext lifecycle;
- Agent/Profile/Origin/expiry/use-count binding;
- Runtime evidence and mismatch detection;
- protected credentials and Human Takeover;
- scoped LocalResourceBroker upload;
- Profile ownership and Agent binding policy;
- user-defined financial limits;
- opaque PaymentInstrumentBroker;
- merchant-saved/system/tokenized payment contract;
- exact single-use step-up grants with URL/document/object binding;
- independently authenticated Visualizer control plane and Safety Center;
- serialized formal Web operation transactions;
- default-disabled primitive Legacy Browser API;
- bounded secret-free SafetyReceipt audit.

P10 `CapabilityEffect` remains unchanged. Business risk dimensions remain in P11 rather than being pushed into the P10 object model.

## Step-up design

Step-up is a scope escalation, not a generic approval token.

Every request is bound to:

```text
Agent
Profile
Origin
WebObject target
semantic operation
SafetyContext when available
requested business scope
redacted exact URL plus opaque URL fingerprint for navigation
WebFA document identity and WebObject version for object operations
expiry
single use
```

Supported reasons include:

```text
financial_limit
financial_assurance
identity_switch
profile_scope
unknown_external_effect
policy_escalation
```

Flow:

```text
operation exceeds current boundary
  -> require_step_up
  -> pending StepUpRequest
  -> Visualizer approves or rejects exact scope
  -> Agent retries the same semantic act request with step_up_id
  -> Runtime verifies binding and scope
  -> operation executes once
  -> grant becomes consumed
```

An approved step-up cannot be reused for a different Agent, Profile, Origin, target, operation, amount, currency, payment instrument, URL fingerprint, document identity, object version, or business effect. Human approval notes remain inside the protected Visualizer and are removed from Agent-facing Step-up responses.

## Safety Center

The Visualizer now includes one integrated Safety Center rather than restoring the legacy transaction approval console.

It provides:

- pending and approved step-up cards;
- exact one-time approve/reject controls;
- current Profile owner/trust/unknown-effect policy;
- Agent and Origin bindings;
- financial-policy configuration;
- safe payment-instrument registration and revoke controls;
- recent SafetyReceipt viewer.

Normal `allow_with_audit` actions do not enter an approval queue.

The complete `/v1/visualizer/*` namespace is a separate human control plane. Every read and mutation requires `X-WebFA-Visualizer-Token`. Electron generates a high-entropy process-local token, starts Runtime with it, injects it only into the trusted local Renderer, blocks cross-location navigation, and validates every IPC sender. A standalone Runtime without an explicitly configured token fails closed for all Visualizer routes.

## SafetyReceipt audit

Every `webfa.act` or `webfa.open_url` request that reaches a P11 safety decision produces a bounded, session-local receipt.

Receipts cover:

```text
allow / allow_with_audit
require_assertion
require_step_up
require_takeover
deny
executed / not_executed / takeover / denied
```

A receipt records only safe metadata:

- Agent and Profile;
- Origin;
- WebObject target and semantic operation;
- P10 effect and P11 dimensions;
- assertion references;
- final decision and result;
- document revisions;
- irreversible authority-source hash reference;
- optional step-up ID;
- timestamp.

Receipts never contain:

- passwords;
- Cookie or token values;
- OTP/2FA values;
- full card numbers;
- CVV/CVC;
- payment passwords;
- wallet tokens;
- bank verification material;
- local absolute file paths.

## Payment acceptance

Real Managed Chromium validation covers:

```text
order total: CNY 279.00
autonomy limit: CNY 100.00
step-up limit: CNY 500.00
payment method: merchant-saved Visa ending in 4821
```

Validated flow:

```text
provide_payment_instrument on the payment option
  -> Runtime observes CNY 279.00
  -> PaymentInstrumentBroker verifies Agent/Profile/Origin/instrument binding
  -> payment option becomes selected
  -> no financial usage is recorded
activate Place order with the same SafetyContext
  -> Runtime re-observes amount and currency
  -> Runtime proves the exact instrument is still selected on the same document
  -> financial policy returns require_step_up for CNY 279.00
  -> UI approves exact amount/document/object scope
  -> Agent retries with context_id + step_up_id
  -> final commit executes once
  -> usage counters update
  -> step-up is consumed
  -> preflight and execution receipts are recorded
```

Low-value final commits inside `autonomy_limit` continue directly with `allow_with_audit`. Deterministic one-click payment controls such as `Pay now with Visa ending in 4821` are classified as final financial commits before activation, so they cannot bypass the financial policy. An unrelated form submit is not charged merely because an order total exists elsewhere on the page.

Payment passwords, 3-D Secure, bank-app confirmation, OTP, and biometric verification remain Human Takeover operations.

## Public interface

The default MCP interface remains exactly five tools:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

No `approve`, `pay`, `authorize`, credential, raw browser, selector, or CDP tool was added. The historical primitive `/v1/browser/legacy/*` endpoints and hidden aliases return `410 legacy_browser_api_disabled` by default; only the explicit unsafe regression switch restores them.

Step-up is carried through the existing safety envelope:

```json
{
  "context_id": "sctx_...",
  "step_up_id": "stepup_..."
}
```

## Validation

Final automated validation:

```text
Python tests:           417 passed
Renderer typecheck:     passed
Electron typecheck:     passed
Python package build:   passed
git diff --check:       passed
```

The only warnings are upstream deprecations from `websockets` and `uvicorn`.

Coverage includes:

- schema and template validation;
- SafetyContext lifecycle;
- Runtime evidence elevation;
- credential and payment takeover;
- local resource upload;
- Profile policy;
- financial policy and payment broker;
- exact Step-up URL fingerprint, document identity, object version, and single-use consumption;
- `open_url` and `act` Origin-scope preflight, approval, and retry;
- two-stage and one-click payment enforcement;
- exact active payment-instrument selection binding;
- serialized safety/execution/accounting transactions;
- bounded SafetyReceipt storage and authority-source hashing;
- authenticated Visualizer reads/mutations and fail-closed token configuration;
- Electron Console navigation and IPC sender restrictions;
- default-disabled Legacy BrowserAction REST;
- concurrent Runtime resource-directory isolation and dead-process cleanup;
- five-tool MCP contract;
- real Managed Chromium payment and upload flows.

## Remaining boundaries

P11 state is session-local:

- SafetyContexts;
- resource grants;
- Profile policy changes;
- financial usage;
- payment-instrument references;
- step-up states;
- SafetyReceipts.

Durable restoration belongs to P13 Durable Trace / Resume.

P11 still uses one active Browser Profile and one active Agent lease. Isolated multi-session and multi-profile execution belongs to P12.

The payment MVP does not provide a local raw-card Vault. It supports safe references for merchant-saved, system-wallet, and tokenized-wallet methods. Issuer virtual-card and prepaid-card provider integrations remain future backend work.

`open_url` and link `open` remain navigation semantics. A site that violates HTTP conventions and performs an external write through GET navigation cannot be classified with complete reliability from protocol shape alone.

Agent identity remains a loopback/local protocol claim rather than a cryptographic principal. The human Visualizer control plane is independently token-protected, but Runtime/MCP should not be exposed directly to an untrusted network.

The explicit historical switch `WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1` deliberately restores primitive calls and therefore voids P11 guarantees for those requests.

Detailed adversarial findings and fixes are recorded in `docs/reports/P11_POST_IMPLEMENTATION_SECURITY_REVIEW.md`.

## Final acceptance

P11 satisfies the frozen product philosophy:

> WebFA tells the Agent what must be checked. The Agent interprets the user conversation. WebFA records the Agent's assertions and enforces only deterministic boundaries.

The phase preserves Agent autonomy while adding enforceable limits around credentials, authentication, identity, local files, recurring commitments, payment instruments, and user-defined financial scope.

Next phase:

```text
P12 Multi Session / Multi Profile
```
