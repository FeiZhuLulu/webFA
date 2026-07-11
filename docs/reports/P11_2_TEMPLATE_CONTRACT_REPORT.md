# P11.2 Template Registry and Contract Compiler Report

Status: complete

## Delivered

Added `packages/webfa-core/browser/safety_templates.py`.

The registry defines versioned, composable, site-independent templates for:

- `identity_context`;
- `financial_commitment`;
- `local_data_egress`;
- `external_representation`;
- `destructive_change`;
- `authority_change`;
- `recurring_commitment`;
- `unknown_external_effect`.

Each template contains:

- machine-readable required assertions;
- deterministic hard-boundary references;
- localized Agent guidance;
- a stable version identifier.

The compiler:

- orders dimensions canonically;
- deduplicates assertions and boundaries;
- never reads user conversation text;
- never uses selectors, URLs, button labels, or site workflows;
- accepts Agent-owned trusted-profile defaults;
- keeps one-time financial commitments separate from recurring commitments.

## Default Behavior

- Agent-owned trusted external representation may compile directly to `ready`.
- Agent-owned trusted `unknown_external_effect` compiles directly to `ready`, producing the `allow_with_audit` path.
- User-owned unknown effects retain an Agent assertion requirement.
- Financial commitments always require explicit transaction/payment and scope assertions.

## Cross-Site Property

The same `financial_commitment.v1` contract is generated regardless of which merchant or website workflow the Agent chooses. Merchant and subject values are scope data, not template selection logic.

## Validation

Covered by `tests/unit/test_safety_templates.py`, including:

- all eight templates present;
- stable versioning and canonical order;
- cross-merchant contract equivalence;
- no site names embedded in templates;
- Agent-owned unknown-effect default behavior;
- deterministic composition and deduplication.
