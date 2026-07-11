# P11 Post-Implementation Security Review

Date: 2026-07-11

Status: completed; blocking findings fixed before commit

Scope:

```text
P11 SafetyContext
Profile and Origin policy
Step-up approval
Visualizer control plane
LocalResourceBroker
PaymentInstrumentBroker and FinancialPolicy
SafetyReceipt audit
Legacy REST compatibility
Electron Runtime/Renderer boundary
```

## Review conclusion

The first P11 implementation passed its functional suite but still contained several security and correctness bypasses that ordinary happy-path tests did not expose. This review treated local Agents and other local processes as potentially untrusted relative to the human Visualizer control plane.

All Critical and High findings identified in this review were fixed before the P11 commit. No known Critical or High issue remains inside the frozen P11 threat model. The remaining boundaries are architectural limitations documented below rather than hidden implementation defects.

## Fixed findings

### 1. Visualizer approval self-service bypass — Critical

**Problem**

`/v1/visualizer/*` originally had no independent authentication. A local Agent with HTTP access could approve its own Step-up, change Profile/financial policy, register payment instruments, or create resource grants.

**Fix**

- all Visualizer reads and mutations require `X-WebFA-Visualizer-Token`;
- the Runtime fails closed when `WEBFA_VISUALIZER_CONTROL_TOKEN` is absent;
- Electron generates a 256-bit random token per process and passes it only to the Runtime environment and trusted Renderer preload path;
- the token is not an Agent ID, SafetyContext value, MCP field, response field, or `NEXT_PUBLIC` build variable.

### 2. Electron Renderer/IPC token exfiltration — Critical

**Problem**

The main BrowserWindow could navigate away from the local Console while retaining preload APIs. IPC handlers did not verify the sender. A remote page loaded into the main window could request the Visualizer control token and invoke Runtime controls.

**Fix**

- Console URL is restricted to loopback HTTP or a local file location;
- new windows are denied;
- cross-location navigation and redirects are denied;
- every Desktop IPC handler validates the exact BrowserWindow sender and Console location;
- file-based Console builds are restricted to the configured Console directory.

### 3. Legacy BrowserAction safety bypass — Critical

**Problem**

The explicit `/v1/browser/legacy/*` endpoints and hidden old aliases could still execute primitive `click/type/press/open` operations, bypassing P11 semantic safety entirely.

**Fix**

- the complete Legacy Browser API returns `410 legacy_browser_api_disabled` by default;
- only historical regression tests may opt in with `WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1`;
- default MCP remains the five formal WebObject tools and never enables the Legacy surface.

### 4. Financial policy applied at payment selection instead of final commit — Critical

**Problem**

Financial usage was checked and recorded when selecting/providing a payment instrument. This produced two inverse failures:

- selecting a card could consume budget before a purchase occurred;
- a site with a default payment method could reach final submit without FinancialPolicy enforcement.

**Fix**

- payment option selection validates bindings but does not record spend;
- final submit/pay activation re-observes amount/currency and evaluates FinancialPolicy immediately before execution;
- one-click `Pay now with ...` controls are classified as final commits before activation;
- usage is recorded only after a successfully executed final commit;
- unrelated form submits are not treated as financial commits merely because the page contains an order total.

### 5. Declared payment instrument not proven selected — High

**Problem**

A final commit could name an `instrument_id` without proving that the page actually used that instrument.

**Fix**

Runtime records a document-scoped selected-payment state only after successful `provide_payment_instrument`. A later final commit that names an instrument must match:

```text
Agent
Profile
Origin
WebFA document identity
payment control identity and active checked/selected state
instrument ID
amount
currency
transaction kind
recurring flag
```

Navigation, reload, deselection, amount change, currency change, or instrument change invalidates the commit.

### 6. Step-up TOCTOU and navigation replay — High

**Problem**

Step-up was bound to Object ID and operation but not to the approved page/object state. Navigation approval was bound only to Origin, so it could be replayed for another path on the same Origin.

**Fix**

- object operations bind `document_id` and `object_version` in exact requested scope;
- navigation binds a redacted exact URL plus an irreversible URL fingerprint;
- amount/currency/instrument/business scopes remain exact;
- scope mismatch leaves the approval unconsumed and blocks execution.

`document_revision` is not used as an implicit approval key because a read-only observe can advance that counter. Agent-supplied `expected_document_revision` remains available in the P10 operation contract.

### 7. Origin scope checked after navigation — High

**Problem**

A SafetyContext Origin mismatch could be detected only after `open_url` had already navigated. The context then remained stuck in `step_up_required` without a complete approval/resume path.

**Fix**

- `open_url` preflights requested Origin and exact URL before navigation;
- the old page remains active while approval is pending;
- approved Origin expansion is applied explicitly to the existing SafetyContext;
- identity/Profile and Origin expansion can be combined into one exact Step-up card;
- the same expansion flow also works for actions after out-of-band/manual navigation.

### 8. Concurrent financial-limit race — High

**Problem**

Two concurrent `act_web` requests could both pass cumulative financial checks before either recorded usage.

**Fix**

Formal `open_web`, `act_web`, and `switch_tab` operations are serialized across the complete transaction:

```text
observe
safety evaluation
step-up validation
browser execution
resource/payment consumption
financial accounting
receipt creation
```

The lock is outside the Driver queue so policy and accounting cannot interleave across requests.

### 9. Local resource deletion and multi-process interference — High

**Problem**

Two opposite lifecycle bugs existed during review:

- deleting a consumed upload file immediately could break browsers that read the file only during final form submit;
- a second Runtime startup could delete files belonging to the first Runtime because all resources shared one directory.

**Fix**

- consumed grants become unusable immediately, but backing data remains until Runtime close so delayed browser reads work;
- revoke and expiry delete immediately;
- each Runtime uses a PID/UUID session directory;
- a new Runtime never deletes a live process's session;
- sessions owned by dead processes are cleaned on the next startup;
- old pre-session resource directories are cleaned only after the maximum resource lifetime;
- Runtime close is serialized with active Web operations and removes its own session directory.

### 10. Audit and approval metadata leakage — Medium

**Problem**

Agent-controlled `authorization_claim.source_ref` could carry arbitrary text into SafetyReceipt. Human `decision_note` and `decided_by` could be returned to the Agent after an approval mismatch.

**Fix**

- receipts store an irreversible short SHA-256 authority reference instead of raw text;
- Agent-facing Step-up state removes human decision metadata;
- the protected Visualizer retains the full local approval record.

## Verification added by the review

The review added or strengthened tests for:

- Visualizer read/write authentication and fail-closed configuration;
- Electron Console navigation and IPC sender restrictions;
- absence of public-build control tokens;
- default-disabled Legacy REST and historical opt-in compatibility;
- two-stage payment selection versus final commit;
- one-click payment preflight;
- default payment FinancialPolicy enforcement;
- exact selected-instrument binding;
- Step-up URL fingerprint, document identity, object version, and single use;
- human approval-note redaction;
- Origin preflight and resumable scope expansion;
- formal-operation serialization;
- resource consume/expiry/revoke/close cleanup;
- dead-process cleanup and concurrent Runtime resource isolation;
- authority-source hashing and payment-secret absence.

## Remaining documented boundaries

### Navigation side effects

`open_url` and link `open` are modeled as navigation. A site can violate HTTP conventions and perform an external write through a GET navigation. WebFA cannot reliably infer that business side effect from URL or protocol shape alone. Deterministic suspicious URL markers would be heuristic and cannot provide a complete guarantee.

### Session-local safety state

SafetyContexts, Step-up states, financial usage, payment references, resource grants, Profile policy changes, and SafetyReceipts are process/session-local. Durable crash restoration and replay-safe continuation belong to P13.

### Single profile and Agent lease

P11 still runs one active Browser Profile and one active Agent lease. Cryptographically isolated multi-session/multi-profile execution belongs to P12.

### Local-process trust boundary

Agent identity is a local protocol claim (`WEBFA_AGENT_ID` / header), not a cryptographic principal. The hard human control plane is independently token-protected, but the Agent REST/MCP service is still designed for loopback/local deployment rather than exposure to an untrusted network.

### Detection limits

Payment, recurring-commitment, and protected-surface classification uses deterministic Runtime evidence and conservative markers. Unknown or opaque states fail toward assertion, Step-up, or Human Takeover, but no marker set can perfectly recover every site's business semantics.

### Explicitly unsafe compatibility switch

`WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1` deliberately restores the old primitive API for historical tests. Enabling it removes P11 guarantees for those calls and is not a supported production configuration.

## Acceptance

P11 is acceptable for commit after the final automated suite, type checks, package build, and Git diff checks pass. The implementation now fails closed at the human control boundary, prevents the identified direct bypasses, and records remaining architectural limits explicitly.
