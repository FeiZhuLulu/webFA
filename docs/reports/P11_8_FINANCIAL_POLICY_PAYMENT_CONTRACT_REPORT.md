# P11.8 Financial Policy & Payment Instrument Contract Report

Status: complete

## Goal

Define deterministic financial limits and a protected payment-instrument contract without storing or exposing raw payment-card secrets.

## Implemented

Added `PaymentInstrumentBroker` and completed the public contract for:

- `FinancialPolicy`;
- `FinancialUsageState`;
- `PaymentInstrumentRef`;
- `PaymentInstrumentState`;
- `provide_payment_instrument` semantic capability.

The payment instrument projection contains only safe metadata:

```text
instrument_id
owner
profile_id
type
brand
last4
currency
policy_id
Agent/Origin bindings
display_name
```

It has no PAN, CVV, payment password, OTP, or wallet token fields. `local_protected_card` is explicitly unavailable in this phase.

## Financial policy

The policy engine enforces user-defined:

- autonomous amount limit;
- normal step-up limit;
- absolute amount limit;
- daily limit;
- monthly limit;
- currency;
- subscription permission;
- transfer permission;
- cash-equivalent permission;
- minimum evidence assurance.

Decisions are deterministic:

```text
within autonomy + sufficient assurance -> allow_with_audit
above autonomy -> require_step_up
above absolute -> deny
daily/monthly projected limit exceeded -> deny
unsupported transaction type -> deny
assurance below policy -> require_step_up
```

No universal definition of “large payment” is hard-coded.

## Runtime amount evidence

`RuntimeEvidenceResolver` recognizes order totals only near conservative markers such as:

```text
Order total
Grand total
Amount due
合计
总计
应付
实付
```

The amount becomes `runtime_observed` evidence. A mismatch between the observed total and the Agent-declared amount or currency is denied.

## Payment capability

Saved-card and wallet controls are compiled as:

```text
provide_payment_instrument
```

They do not also expose ordinary `activate` or `toggle`, preventing the Agent from bypassing the payment Broker on recognized payment-method controls.

Arguments are:

```text
instrument_id
amount
currency
transaction_kind
recurring?
```

The Agent supplies an opaque reference, never a payment secret.

## Validation

Validated:

- low-value payment allowed and usage recorded;
- autonomous-limit overflow returns step-up;
- absolute-limit overflow denies;
- insufficient assurance returns step-up;
- subscription, transfer, cash-equivalent, Origin, Agent, Profile, target-label, and currency policies are enforced;
- tokenized-wallet references are supported without exposing wallet tokens;
- local raw-card Vault remains disabled.
