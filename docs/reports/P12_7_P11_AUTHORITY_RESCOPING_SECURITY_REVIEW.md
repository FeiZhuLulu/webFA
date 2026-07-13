# P12.7 P11 Authority Re-scoping and Security Review

Status: implemented; full acceptance pending P12.8

Date: 2026-07-13

## 1. Scope

P12.7 re-scopes P11 short-lived authority objects for the multi-Profile and multi-Session Runtime introduced by P12.1-P12.6.

The security objective is:

```text
An authority object created in one Agent connection, Browser Profile,
Browser Session, or Runtime generation must not be reusable in another.
```

The default Agent MCP surface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

No Session, Profile, Cookie, Storage, approval, or raw browser tool was added.

## 2. Trusted Runtime Authority Scope

P12.7 defines the internal authority tuple:

```text
agent_id
connection_id
profile_id
session_id
runtime_generation
```

Additional operation bindings are applied where relevant:

```text
origin
document_id
target_object_id
semantic operation
requested scope
expiry
remaining uses
```

`connection_id`, `session_id`, and `runtime_generation` are not model-supplied tool arguments. They are derived from the authenticated MCP/HTTP transport and the selected `BrowserSessionRuntime`.

The new `RuntimeAuthorityScope` value object documents and validates this trusted boundary. The Runtime uses `normalize_connection_id()` only for legacy direct-call compatibility; production Supervisor routing always supplies the real connection ID.

## 3. SafetyContext

Each managed SafetyContext now stores:

```text
connection_id
session_id
runtime_generation
```

The active-context index is keyed by:

```text
(agent_id, connection_id, profile_id, session_id, runtime_generation)
```

All context operations validate this binding:

- declaration and assertion;
- existing-context evaluation;
- Runtime evidence application;
- origin-scope extension;
- context consumption;
- current-state projection;
- declaration lookup used by payment and upload validation.

A binding mismatch fails the current request without mutating the original context. This prevents a hostile or accidental second connection from permanently changing the rightful owner’s context to `blocked`.

Agent-visible `SafetyContextState` now includes `session_id` and `runtime_generation`, but never exposes `connection_id`.

## 4. Step-up Grants

Step-up requests now bind:

```text
agent_id
internal connection_id
profile_id
session_id
runtime_generation
origin
document_id
target_object_id
semantic operation
context_id
exact requested scope
```

The connection ID is stored only in the local manager’s authoritative state. The public `StepUpRequest` projection includes Session, generation, origin, document, target, and operation, but not the connection credential.

Authorization and consumption reject:

- another Agent connection;
- another document;
- another target or operation;
- another exact scope;
- another Profile;
- another Session or Runtime generation;
- expired, rejected, or consumed grants.

Approved grants remain single-use by default.

## 5. LocalResourceGrant

Local resource grants now carry:

```text
profile_id
session_id
runtime_generation
```

The first valid authorization pins the resource to an Agent connection. Validation order was deliberately hardened:

1. expiry and use count;
2. Agent binding;
3. Profile binding;
4. origin binding;
5. purpose binding;
6. Runtime Session/generation binding;
7. backing-file existence;
8. connection pinning.

An invalid caller therefore cannot claim the connection binding before failing another scope check.

Resource consumption requires the same connection, Session, and Runtime generation that successfully authorized the resource.

Backing paths remain absent from Agent-visible and Control Center projections.

## 6. Payment Authority

Persistent `PaymentInstrumentRef` remains Profile-scoped rather than Session-scoped. This is intentional: a saved payment method is durable Profile configuration.

Short-lived payment authority is now bound through an internal fingerprint:

```text
(agent_id, connection_id, profile_id, session_id, runtime_generation)
```

This fingerprint is attached to:

- `PaymentAuthorization`;
- `FinancialAuthorization`;
- selected-payment state retained between payment selection and final commit.

The final financial-use recording path validates the current trusted scope against the authorization fingerprint. A payment authorization cannot be committed from another connection or after a Session generation replacement.

Selected payment state additionally remains bound to:

```text
document_id
origin
instrument_id
amount
currency
transaction kind
recurring flag
selected WebObject
```

The durable instrument never contains card secrets or wallet tokens; only the existing opaque reference and safe display metadata remain available.

## 7. SafetyReceipt

Every new SafetyReceipt now records:

```text
profile_id
session_id
runtime_generation
origin
document_id
target_object_id
operation
```

`SafetyReceiptStore` is constructed for one explicit Session generation and rejects receipts from any other binding. It also retains an internal connection association without exposing that identifier in the receipt schema.

Receipts remain secret-free. They do not contain:

- Cookie values;
- authorization headers;
- passwords;
- payment tokens;
- local paths;
- human input values;
- raw Monitor credentials.

## 8. Runtime Propagation

The trusted connection identity now flows through:

```text
MCP Runtime Client
  -> internal X-WebFA-Connection-Id header
  -> BrowserRuntimeSupervisor AgentConnectionContext
  -> BrowserSessionRuntime
  -> P11 authority managers
```

The model never supplies or edits this value.

`open_web`, `observe_web`, and `act_web` now receive the connection binding from the Supervisor. Legacy direct tests and compatibility entry points retain deterministic fallback behavior without weakening production Supervisor routing.

## 9. Adversarial Tests

New tests verify:

1. A SafetyContext from connection A is denied to connection B.
2. The denied attempt does not poison or consume connection A’s context.
3. A Step-up from connection A cannot be authorized or consumed by connection B.
4. A Step-up cannot move to another document.
5. A LocalResource invalid caller cannot claim its connection binding.
6. A valid LocalResource authorization cannot be replayed by another connection.
7. A payment authorization cannot be recorded by another connection.
8. A payment authorization cannot be recorded in a replacement Runtime generation.
9. A SafetyReceiptStore rejects a receipt from another generation.
10. Existing single-Session and multi-Session behavior remains compatible.

## 10. Validation

P12.7 implementation validation:

```text
Python tests:          482 passed
Electron typecheck:    passed
Renderer typecheck:    passed
Python package build:  passed
MCP integration:       passed
Git diff check:        passed
Existing warnings:       2 upstream deprecation warnings
```

The warnings remain unchanged:

- `websockets.legacy` deprecation;
- Uvicorn legacy WebSocket protocol import.

The public MCP schema remains unchanged except for the already accepted optional `profile_ref` on `webfa.open_url`. A final source scan confirmed that safety authority projections do not expose the internal connection ID, Cookie values, authorization headers, payment tokens, human input values, or local resource paths.

## 11. Remaining P12 Boundary

P12.7 completes authority re-scoping. It does not add durable Session resume; active grants remain intentionally invalid after Runtime restart.

P12.8 remains responsible for final acceptance and migration review:

- full build and contract validation;
- real Chromium multi-Profile scenarios;
- default Profile migration verification;
- crash and lease-race review;
- secret/path leakage review;
- final maintenance report.

Cookie import remains Post-Core Profile Bootstrap work. It will consume the Profile isolation and mutation-lock model after P12 Core acceptance.
