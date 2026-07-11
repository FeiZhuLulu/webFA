# P11.1 Schema Foundation Report

Status: complete

## Delivered

Added `packages/schemas/safety.py` with the complete P11 target schema:

- eight discriminated safety dimensions;
- `SafetyDeclaration`;
- `SafetyContract`;
- `SafetyAssertionSet`;
- `SafetyOperationEnvelope`;
- `SafetyContextState`;
- `SafetyDecision`;
- `SafetyReceipt`;
- `ProfileOwnershipMetadata`;
- `FinancialPolicy`;
- `PaymentInstrumentRef`;
- `LocalResourceGrant`.

Extended the public Web Object protocol without changing the five-tool model:

- `WebOpenRequest.safety`;
- `WebState.safety`;
- `WebOperationRequest.expected_document_revision`;
- `WebOperationRequest.safety`;
- `WebOperationResult.safety_decision`;
- `WebOperationResult.safety_receipt`;
- `WebOpenResult`.

## Frozen Defaults

- `trusted_agent` is the default trust mode.
- Agent-owned profiles default `unknown_external_effect` to `allow_with_audit`.
- Payment instruments expose only opaque references and safe metadata.
- Financial thresholds are user-configured; WebFA defines no universal large-amount threshold.

## Compatibility

P10 `CapabilityEffect` remains unchanged. P11 business-risk dimensions are a separate layer and do not introduce purchase, subscription, or other business terms into P10 capability metadata.

Existing requests remain valid because every P11 field added to the Web protocol is optional.

## Validation

Covered by:

- `tests/unit/test_safety_schemas.py`;
- existing WebObject schema and security contract tests;
- MCP schema regression confirming the five public tools remain unchanged.
