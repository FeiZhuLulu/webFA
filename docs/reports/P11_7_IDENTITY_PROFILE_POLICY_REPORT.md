# P11.7 Identity & Profile Policy Report

Status: complete

## Goal

Make the active Browser Profile an explicit safety principal with deterministic ownership, Agent binding, trust mode, origin scope, and unknown-effect policy, without prematurely implementing P12 multi-profile browser isolation.

## Implemented

Added `ProfilePolicyStore` with version-compatible `ProfileOwnershipMetadata`:

- `profile_id`;
- `owner`: `agent_owned`, `user_owned`, `shared`, or `unknown`;
- `bound_agent_ids`;
- `allowed_origins`;
- `trust_mode`;
- `unknown_external_effect_policy`;
- optional safety and financial policy references.

The current `BrowserAgentState`, Runtime status, and Visualizer state now expose safe Profile metadata so an Agent can construct a declaration that matches the actual Profile policy.

## Hard-boundary behavior

Before a protected semantic operation, WebFA verifies:

- active Agent is allowed by the Profile;
- current Origin is inside the Profile scope when configured;
- `SafetyDeclaration.account_owner` matches the Profile owner;
- declared trust mode matches the Profile trust mode;
- use of an existing account matches Profile ownership.

Mismatch produces a deterministic `deny`, not an LLM judgment.

## Identity switch behavior

For a `user_owned` Profile, these declared identity actions require step-up:

```text
sign_in
switch_account
create_account
authorize_third_party
```

This is scope escalation rather than duplicate task approval. Agent-owned Profiles remain configurable and less restrictive.

## Unknown external effects

Frozen default behavior is implemented:

```text
agent_owned + trusted_agent -> allow_with_audit after task declaration
shared -> assertion policy
user_owned -> require_step_up
```

A SafetyContext is still required for a Runtime-observed external mutation. `allow_with_audit` means the Agent declaration does not require a second WebFA UI approval; it does not mean undeclared writes execute silently.

## P12 boundary

P11.7 stores and enforces policy for the current Profile only. It does not create multiple Chromium profiles, switch browser storage partitions, or implement profile locks. Those remain P12.

## Validation

Validated:

- Agent-owned unknown external effect executes with audit after declaration;
- user-owned identity switch returns `require_step_up` and does not execute;
- Agent binding mismatch denies;
- Profile owner mismatch denies;
- trust-mode mismatch denies;
- Profile policy metadata is projected through Runtime and Visualizer.
