# P11.5 Credential & Human Takeover Boundary Report

Status: complete

## Goal

Turn credentials and human verification into deterministic Runtime boundaries. Agent code may use an authenticated Profile, but protected secrets and verification steps must not become ordinary `set_value` operations.

## Implemented

WebObject security now identifies protected inputs:

```text
password
one_time_code
captcha
payment_card
payment_verification
biometric_verification
```

Protected objects:

- expose no editable `set_value` or `clear_value` capability;
- expose `request_human_takeover` only;
- carry `security.protected_input=true` and a typed `protected_kind`;
- map to a typed takeover reason.

Takeover reasons added:

```text
payment_verification
biometric_verification
```

Existing reasons remain available for authentication and CAPTCHA.

## Secret redaction

The collection and projection pipeline now scrubs values for:

- password fields;
- one-time-code/OTP/2FA fields;
- CAPTCHA-like fields;
- card number/CVV/CVC fields;
- payment-password fields;
- file-input values.

Action log redaction also covers card number, CVV/CVC, OTP, and verification-code keys.

## Runtime behavior

Examples:

```text
password / OTP       -> authentication takeover
CAPTCHA              -> captcha takeover
card/payment secret  -> payment_verification takeover
biometric control    -> biometric_verification takeover
```

The user completes the challenge in the WebFA takeover surface. This is not a second task-authorization approval; it is completion of a human-only authentication or payment challenge.

## Validation

A real Managed Chromium fixture contains prefilled password, OTP, card number, CVV, payment password, CAPTCHA, and biometric controls.

Validated:

- secret values do not appear in WebState;
- card fields declare only `request_human_takeover`;
- card fields request `payment_verification` takeover;
- takeover output contains no card number or payment secret;
- Renderer displays reason-specific instructions.

## Boundaries

P11.5 deliberately treats raw card-entry fields as human-only. A future `PaymentInstrumentBroker` in P11.8/P11.9 may activate tokenized or merchant-saved instruments without exposing secrets, but it will not re-enable Agent-readable card values.
