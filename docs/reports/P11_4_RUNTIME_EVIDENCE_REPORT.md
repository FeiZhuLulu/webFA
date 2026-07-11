# P11.4 Runtime Evidence & Mismatch Detection Report

Status: complete

## Goal

Add deterministic Runtime evidence to the P11 Safety Contract without adding an LLM, site-specific business flows, selectors, or a sixth MCP tool.

## Implemented

- Added `SafetyEvidenceItem`, `SafetyMismatch`, and `SafetyEvidenceReport`.
- Added `RuntimeEvidenceResolver` over P10 WebObjects and capability effects.
- Runtime evidence can add safety dimensions but can never remove an Agent-declared dimension.
- SafetyContext now records:
  - declared dimensions;
  - observed dimensions;
  - evidence items;
  - mismatch records;
  - minimum assurance.
- Added contract extension for dimensions discovered after the initial declaration.
- Added evidence for:
  - P10 capability effects;
  - external form submission;
  - upload targets;
  - protected credentials;
  - authentication/CAPTCHA surfaces;
  - payment and payment-verification surfaces;
  - recurring-commitment markers;
  - authority/destructive/external-send effects.

## Runtime behavior

For an HTTP(S) external mutation with no SafetyContext:

```text
require_assertion
status = undeclared
executed = false
```

For an Agent-owned trusted Profile with a declared `unknown_external_effect`:

```text
allow_with_audit
```

The Runtime does not identify arbitrary business intent. An external form submit is conservatively classified as `unknown_external_effect` unless stronger deterministic evidence exists.

## Evidence assurance

Current levels used in this phase:

```text
agent_asserted
runtime_observed
provider_verified
```

`provider_verified` is currently used by the LocalResourceBroker after validating an opaque resource grant.

## Validation

- Unit tests cover external submit, protected payment, upload, form-submit activation, and local-file non-external behavior.
- Real Managed Chromium REST test verifies:
  - external submit without SafetyContext is not executed;
  - Agent-owned trusted unknown effect executes after declaration;
  - the default five MCP tools remain unchanged.

## Boundaries

P11.4 does not yet implement generalized amount extraction, merchant verification, or financial-limit evaluation. Those remain P11.8 concerns. Marker evidence is explicit `runtime_observed` evidence, not business-level proof.
