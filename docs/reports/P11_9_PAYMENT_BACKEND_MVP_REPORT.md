# P11.9 Payment Backend MVP Report

Status: complete

## Goal

Complete the first real protected-payment path while preserving WebFA's five-tool Agent surface and keeping payment secrets outside Agent-visible state.

## Supported MVP backends

The Broker currently accepts:

```text
merchant_saved
system_wallet
tokenized_wallet
```

The real Managed Chromium acceptance path uses a merchant-saved method. System/tokenized wallet controls use the same opaque-reference and policy contract and are covered by Broker tests. Issuer virtual cards and prepaid references remain defined in the target schema but require a future provider integration. Local protected card storage is disabled.

## Real execution path

```text
Agent observes payment-method WebObject
  -> WebObject declares provide_payment_instrument only
  -> Agent submits financial SafetyContext and assertions
  -> Runtime observes order total
  -> Profile policy is checked
  -> PaymentInstrumentBroker checks instrument binding and target label
  -> FinancialPolicy checks amount, currency, assurance, transaction type, and cumulative limits
  -> BrowserHost activates the merchant-saved payment control
  -> usage ledger is updated
  -> secret-free SafetyReceipt is returned
```

## Merchant-saved method validation

The Broker verifies the selected target against safe instrument metadata such as brand and last four digits. A target that does not match the bound instrument is denied.

The Agent receives:

```text
instrument type
brand
last4
amount
currency
transaction kind
assurance
usage totals
```

It never receives the underlying card number, CVV, wallet token, payment password, or authentication material.

## Payment challenges

Raw card fields, payment passwords, 3-D Secure, bank verification, biometric confirmation, and other payment challenges remain `Human Takeover`. P11.9 does not automate or bypass them.

## Receipt

A successful payment operation returns a `SafetyReceipt` containing:

- context, Agent, Profile, Origin;
- target WebObject and semantic operation;
- P10 effect and active safety dimensions;
- assertion identifiers;
- document revisions;
- final execution decision.

The receipt does not contain the payment-instrument ID or any payment secret. Durable storage and receipt browsing remain P11.10/P13 work.

## Real-browser acceptance

Validated with a real HTTP fixture and Managed Chromium:

- Runtime identifies `Order total: CNY 279.00`;
- saved method `Visa ending in 4821` declares only `provide_payment_instrument`;
- an Agent-owned trusted Profile and CNY 300 autonomous limit allow the operation;
- the website reports successful payment activation;
- the policy usage ledger records CNY 279.00;
- response and receipt contain no raw card fields or secrets.

## Boundaries

This MVP proves protected instrument selection and policy-governed activation. It is not a card processor, settlement verifier, chargeback system, fraud engine, or universal payment-site adapter.
