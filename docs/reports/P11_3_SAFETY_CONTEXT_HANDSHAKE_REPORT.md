# P11.3 SafetyContext Handshake Report

Status: complete

## Delivered

Added `packages/webfa-core/browser/safety_context.py` and integrated it into the public WebFA Runtime path.

The implemented handshake is:

```text
SafetyDeclaration
  -> compiled SafetyContract
  -> Agent assertions
  -> ready / allow_with_audit
  -> semantic operation
  -> context consumption
```

Supported paths:

- declaration only, returning `assertion_required`;
- existing `context_id` reference;
- assertion submission for an existing context;
- trusted fast path with declaration and assertions in one request;
- read-only safety projection through `WebState.safety`.

## Lifecycle and Binding

SafetyContext is bound to:

- active Agent ID;
- profile ID;
- origin scope;
- expiry;
- remaining use count.

Implemented states include:

- `assertion_required`;
- `ready`;
- `step_up_required`;
- `blocked`;
- `consumed`;
- `expired`.

Implemented checks include:

- Agent/profile mismatch denial;
- origin-scope escalation;
- expiry;
- max-use consumption;
- host-attested mode requiring a non-expired attestation;
- explicit `not_granted` declarations remaining blocked.

## Public Protocol

The default MCP surface remains exactly five tools.

`webfa.open_url` now accepts optional `safety` data and can establish a context after navigation.

`webfa.act` now accepts:

- `expected_document_revision`;
- optional `safety.declaration`;
- optional `safety.assertions`;
- optional `safety.context_id`.

A pending safety contract returns an unexecuted result with the contract and safety state. A ready context permits execution and is consumed according to its configured use count.

`webfa.observe` remains read-only and only projects current safety state.

## P10 Integrity

- WebObjects remain the only page-object model.
- Semantic Operations remain the only public action model.
- Browser primitives remain internal.
- No new public MCP tool was introduced.
- Legacy REST endpoints remain isolated.

## Validation

Validation includes:

- unit lifecycle tests in `tests/unit/test_safety_context.py`;
- document-revision conflict coverage in semantic operation tests;
- real Managed Chromium REST handshake regression;
- MCP stdio schema and normal-flow regression;
- complete Python suite: 362 tests passed at final P11.1-P11.3 acceptance.
- Electron and Renderer typechecks passed.
- `python -m build` passed and included the new safety modules.
