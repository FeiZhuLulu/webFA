# P11 Agent Safety Contract & Hard Boundaries

Status: historical design draft; P11.0-P11.10 implementation is complete. See docs/p11plan.md and docs/reports/CURRENT_BASELINE.md.

Working name:

```text
P11 Agent Safety Contract & Hard Boundaries
Agent 安全契约与硬边界
```

P11 does not turn WebFA into an intelligent approval agent. WebFA still has no LLM and does not interpret the user's natural-language conversation.

P11 establishes a deterministic protocol in which:

```text
User gives intent and authority to the Agent
Agent interprets that authority
Agent declares the task's safety dimensions to WebFA
WebFA returns machine-readable safety obligations
Agent asserts whether the obligations are satisfied
WebFA enforces only deterministic hard boundaries
WebFA executes the page operation and records a receipt
```

The default experience should preserve Agent autonomy. A WebFA approval card is a fallback for scope escalation, missing authority, or a hard boundary; it is not a mandatory second confirmation for every real-world action.

---

## 1. Product Goal

P10 answered:

```text
How does an Agent read and operate a real webpage through WebObjects?
```

P11 answers:

```text
How can an Agent act freely on the real web while receiving consistent safety obligations and respecting a small set of enforceable user boundaries?
```

The target result is:

```text
Agent conversation and task context
  -> SafetyDeclaration
  -> SafetyTemplateRegistry
  -> SafetyContract
  -> AgentAssertions
  -> HardBoundaryEngine
  -> Semantic WebOperation
  -> SafetyReceipt
```

P11 must work across arbitrary websites without maintaining site-specific operation allowlists.

---

## 2. Core Decisions

### 2.1 WebFA does not interpret user intent

WebFA does not decide whether:

- the user really wanted to buy an item;
- a message is appropriate;
- a post is offensive;
- a deletion is sensible;
- an Agent's plan is good.

Those decisions belong to the Agent layer, which has the user conversation and reasoning capability.

### 2.2 WebFA returns obligations, not business judgments

WebFA deterministically maps declared and observed risk dimensions to a versioned safety contract.

Example:

```text
financial_commitment
  -> confirm explicit purchase authority
  -> confirm explicit payment authority
  -> confirm amount is in scope
  -> confirm no unapproved recurring charge
```

The contract is returned as both:

- localized natural-language guidance for the Agent;
- machine-readable required assertions.

### 2.3 Agent assertions are accepted in the normal trusted-agent path

In the default trusted-agent mode, the Agent may assert that the user has already granted the necessary authority. WebFA records the assertion and does not repeat the approval in its own UI.

This is intentionally a trust model, not proof that the Agent interpreted the user correctly.

### 2.4 WebFA enforces only deterministic hard boundaries

Hard boundaries are limited to conditions WebFA can verify without an LLM, including:

- credential secrecy;
- password, 2FA, CAPTCHA, biometric, and payment-challenge takeover;
- profile and identity binding;
- local resource grants;
- user-configured financial limits;
- separate authorization for recurring commitments;
- protected payment-instrument use;
- explicit deny policies.

### 2.5 No site-specific operation lists

WebFA does not encode:

```text
Taobao purchase steps
JD purchase steps
Amazon purchase steps
Gmail send steps
GitHub delete steps
```

The Agent navigates each site's unique workflow through P10 WebObjects. P11 standardizes the safety dimensions and boundaries around the effect, not the sequence of buttons.

### 2.6 Default MCP surface remains five tools

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

P11 extends request and response envelopes. It does not add a separate approval or payment MCP tool.

---

## 3. Responsibility and Trust Model

### 3.1 User

The user:

- grants authority through the Agent conversation;
- configures long-term WebFA hard boundaries;
- chooses Agent identities, profiles, resources, and payment instruments;
- completes human-only authentication and payment verification;
- may deliberately select permissive policies for trusted Agents.

### 3.2 Agent

The Agent:

- interprets the user's natural-language instruction;
- chooses the website and workflow;
- declares relevant safety dimensions;
- reads WebFA safety obligations;
- asserts whether the user has granted the required authority;
- stops and asks the user when it cannot make a reliable assertion;
- remains responsible for planning and business semantics.

### 3.3 Agent Host

The Agent Host may optionally provide stronger assurance by binding an assertion to:

- an Agent identity;
- a conversation or task ID;
- a user-turn reference;
- a timestamp and expiry;
- a signed or locally attested declaration.

Host attestation is optional in P11 and must not be required for ordinary trusted-agent use.

### 3.4 Web content

All webpage content is untrusted data.

A page cannot:

- grant authority;
- alter a SafetyContext;
- satisfy an Agent assertion;
- request payment secrets;
- expand file access;
- increase a financial limit;
- switch identity ownership.

### 3.5 WebFA Runtime

WebFA:

- owns the deterministic template registry;
- owns hard-boundary policy;
- binds safety state to the current Runtime session, Agent, profile, and origin;
- prevents secrets from entering Agent-visible state;
- brokers protected resources;
- records structured receipts.

### 3.6 Payment and identity providers

Banks, wallets, issuers, authenticators, and websites may require user verification independently of WebFA. Those challenges are treated as Human Takeover, not as a second interpretation of user intent.

---

## 4. Architecture

```text
Agent / Agent Host
  |
  | SafetyDeclaration + WebOperation
  v
SafetyContextManager
  |
  +--> SafetyTemplateRegistry
  |      deterministic templates and assertion requirements
  |
  +--> RuntimeEvidenceResolver
  |      P10 effects, origins, object relations, protected fields,
  |      payment surfaces, file inputs, dialogs, profile metadata
  |
  +--> HardBoundaryEngine
  |      credentials, takeover, profile, files, financial limits,
  |      recurring commitments, explicit deny policies
  |
  +--> Protected Resource Brokers
  |      CredentialBroker
  |      PaymentInstrumentBroker
  |      LocalResourceBroker
  |
  +--> SafetyDecision
  |      inform / require_assertion / allow_with_audit /
  |      step_up / takeover / deny
  v
SemanticOperationExecutor
  v
SafetyReceiptStore
```

### 4.1 SafetyContextManager

Maintains a task-scoped safety state bound to:

```text
runtime session
agent id
profile id
origin set
creation time
expiry
```

It accepts declarations and assertions, compiles contracts, tracks pending obligations, and produces a compact safety projection in WebState.

### 4.2 SafetyTemplateRegistry

A versioned registry of generic risk dimensions and their required assertions.

Templates contain no site-specific selectors, URLs, button labels, or flows.

### 4.3 RuntimeEvidenceResolver

Collects deterministic evidence from P10 and BrowserHost internals. It does not infer arbitrary business meaning.

Evidence examples:

- current origin and frame origin;
- P10 capability effect;
- form and submit-control relation;
- upload target;
- password or protected credential field;
- Payment Request API invocation;
- Secure Payment Confirmation or WebAuthn challenge;
- card-related autocomplete metadata;
- current profile and profile owner;
- user-approved resource reference;
- Runtime-observed amount and currency when reliably available.

### 4.4 HardBoundaryEngine

Evaluates hard policy without natural-language reasoning.

### 4.5 Protected Resource Brokers

Agents reference protected resources by opaque IDs. They never receive underlying secret values or unrestricted filesystem paths.

### 4.6 SafetyReceiptStore

Records important safety events and final operations. P11 defines the receipt schema. Receipts remain session-local; durable resume is not a product phase.

---

## 5. Safety Dimensions and Templates

Safety dimensions are composable. One task may activate several templates.

The complete P11 model defines eight dimensions. Initial engineering may implement the first three, but the public schema must be complete from P11.1.

### 5.1 `identity_context`

Describes whose online identity is being used and whether an identity transition is occurring.

```text
account_owner:
  agent_owned
  user_owned
  shared
  unknown

action:
  use_existing_account
  sign_in
  switch_account
  create_account
  authorize_third_party
```

Required assertions may include:

```text
current_identity_matches_task
user_authorized_use_of_user_identity
no_unapproved_identity_switch
```

Hard boundaries:

- secrets are never returned to the Agent;
- authentication challenges require Human Takeover;
- profile switching must satisfy profile binding policy.

### 5.2 `financial_commitment`

Describes a real monetary commitment.

```text
kind:
  one_time_purchase
  transfer
  refund
  bid
  donation
  paid_service
  cash_equivalent
  unknown_financial_commitment
```

Fields may include:

```text
currency
estimated_amount
maximum_amount
merchant
item_summary
quantity
payment_instrument_ref
```

Required assertions may include:

```text
user_explicitly_authorized_purchase
user_explicitly_authorized_payment
actual_amount_within_authorized_scope
merchant_and_subject_match_task
```

Hard boundaries:

- payment-instrument policy;
- user-defined amount limits;
- payment challenge takeover;
- transfers and cash equivalents disabled unless explicitly enabled.

### 5.3 `local_data_egress`

Describes local or user-controlled data leaving the device or WebFA environment.

```text
source_owner:
  agent
  user
  shared

resource_refs
Destination origin
Purpose
```

Required assertions may include:

```text
user_authorized_specific_resources
user_authorized_destination
resource_use_matches_task
```

Hard boundaries:

- only LocalResourceBroker references may be uploaded;
- raw arbitrary filesystem paths are rejected;
- destination-origin and use-count restrictions are enforced.

### 5.4 `external_representation`

Describes the Agent communicating or making a representation under an identity.

```text
kind:
  email
  direct_message
  public_post
  comment
  application
  form_submission
  support_request
  legal_or_policy_acknowledgement
```

Required assertions may include:

```text
user_authorized_external_communication
identity_and_audience_match_task
content_or_subject_is_within_scope
```

Agent-owned communication accounts may be configured as permissive.

### 5.5 `destructive_change`

Describes deletion, cancellation, overwriting, revocation, or another potentially irreversible change.

```text
resource_owner
resource_ref
reversible
recovery_window
```

Required assertions may include:

```text
user_authorized_destructive_effect
resource_matches_task
recovery_expectation_is_understood
```

Agent-owned temporary resources may be allowed with audit only.

### 5.6 `authority_change`

Describes changes that alter future access or security authority.

```text
kind:
  add_member
  change_role
  grant_admin
  create_credential
  authorize_application
  change_security_setting
  change_recovery_method
  make_public
```

Required assertions may include:

```text
user_authorized_authority_change
new_principal_and_scope_match_task
```

Credential creation and recovery-method changes may require Human Takeover or explicit step-up policy.

### 5.7 `recurring_commitment`

Recurring commitments are separate from a one-time purchase.

```text
kind:
  subscription
  automatic_renewal
  installment_plan
  recurring_donation
  recurring_service

interval
amount_per_interval
minimum_term
cancellation_terms_known
```

A one-time purchase declaration never authorizes a recurring commitment.

Required assertions may include:

```text
user_explicitly_authorized_recurring_commitment
interval_and_amount_match_scope
cancellation_terms_are_within_scope
```

### 5.8 `unknown_external_effect`

Used when an operation changes the external world but cannot be reliably classified.

This is not automatically denied.

Policy examples:

```text
agent-owned profile -> allow_with_audit
shared profile -> require_agent_assertion
protected user profile -> require_step_up
```

---

## 6. Relationship to P10 Capability Effects

P10 `CapabilityEffect` remains a low-level, deterministic minimum effect:

```text
read
navigation
local_state_change
external_write
external_send
download
upload
destructive
permission_change
unknown
```

P11 safety dimensions are a separate layer. They must not overload the P10 effect enum with business-specific meaning.

Example:

```text
P10 operation: activate
P10 minimum effect: external_write
Agent safety declaration: financial_commitment(one_time_purchase)
Runtime evidence: payment surface, total CNY 279
Effective dimensions: identity_context + financial_commitment
```

The effective dimension set is:

```text
declared dimensions
UNION runtime-detected dimensions
UNION dimensions required by active profile policy
```

Runtime evidence may add or elevate obligations. It may never silently remove an Agent-declared risk.

If WebFA detects upload, protected credentials, payment verification, or another hard signal missing from the declaration, it returns `safety_declaration_incomplete` with the additional required dimension.

---

## 7. Agent Safety Handshake

### 7.1 Phase A: Declaration

The Agent submits a task-scoped declaration.

```json
{
  "mode": "declare",
  "principal": {
    "agent_id": "shopping-agent",
    "profile_id": "profile-agent-shopping"
  },
  "task": {
    "intent": "purchase_product",
    "subject": "A商品"
  },
  "dimensions": [
    {
      "type": "identity_context",
      "account_owner": "agent_owned",
      "action": "use_existing_account"
    },
    {
      "type": "financial_commitment",
      "kind": "one_time_purchase",
      "currency": "CNY",
      "maximum_amount": "300.00",
      "quantity": 1
    }
  ],
  "authorization_claim": {
    "status": "explicit",
    "source_ref": "user_turn_42"
  },
  "expires_in_seconds": 3600
}
```

The Agent's `intent` and `subject` are informational and auditable. WebFA does not semantically verify them.

### 7.2 Phase B: Contract

WebFA compiles and returns:

```json
{
  "context_id": "sctx_01",
  "status": "assertion_required",
  "templates": [
    "identity_context.v1",
    "financial_commitment.v1"
  ],
  "required_assertions": [
    "current_identity_matches_task",
    "user_explicitly_authorized_purchase",
    "user_explicitly_authorized_payment",
    "actual_amount_within_authorized_scope",
    "no_unapproved_recurring_commitment"
  ],
  "hard_boundaries": [
    "credential_secrecy",
    "financial_policy",
    "payment_challenge_takeover"
  ],
  "instruction": "该任务涉及真实身份和资金承诺……"
}
```

### 7.3 Phase C: Assertions

The Agent evaluates its conversation context and submits assertions.

```json
{
  "mode": "assert",
  "context_id": "sctx_01",
  "assertions": {
    "current_identity_matches_task": true,
    "user_explicitly_authorized_purchase": true,
    "user_explicitly_authorized_payment": true,
    "actual_amount_within_authorized_scope": true,
    "no_unapproved_recurring_commitment": true
  },
  "authorization_source": "user_turn_42"
}
```

False or omitted assertions keep the context pending. The Agent should stop and ask the user.

### 7.4 Phase D: Reference during operations

Subsequent operations reference only the context:

```json
{
  "target": "obj_confirm_order",
  "operation": "activate",
  "safety": {
    "context_id": "sctx_01"
  }
}
```

### 7.5 Fast path

A trusted Agent may send declaration and assertions together. WebFA compiles the same contract internally and evaluates it without requiring a second round trip when all obligations are satisfied.

The response still includes the compiled contract and final receipt so the process remains inspectable.

### 7.6 Context invalidation

A SafetyContext must be re-evaluated when any bound condition changes materially:

- Agent ID;
- profile ID;
- account ownership;
- origin outside declared scope;
- declared amount or currency;
- recurring commitment appears;
- new local resource is added;
- task expiry;
- use count exhausted;
- document state reveals a new hard boundary.

---

## 8. Safety Context Lifecycle

```text
undeclared
  -> assertion_required
  -> ready
  -> operation_allowed
  -> active / partially_consumed
  -> consumed / expired

assertion_required
  -> step_up_required
  -> takeover_required
  -> blocked
```

Status enum:

```text
undeclared
assertion_required
ready
step_up_required
takeover_required
blocked
consumed
expired
```

Decision enum:

```text
inform
require_assertion
allow
allow_with_audit
require_step_up
require_takeover
deny
```

The normal autonomous path should end in `allow_with_audit`, not `require_step_up`.

---

## 9. Public Protocol Integration

P11 preserves the five public MCP tools.

### 9.1 `webfa.open_url`

May accept an optional initial declaration:

```json
{
  "url": "https://example.com",
  "safety": {
    "declaration": {}
  }
}
```

This is convenient when a task begins with navigation.

### 9.2 `webfa.act`

May accept one of:

```text
safety.declaration
safety.assertions
safety.context_id
```

A risky operation without sufficient safety state is not executed. The result returns the missing contract or boundary condition.

### 9.3 `webfa.observe`

Remains read-only. It returns the current safety projection but does not mutate a SafetyContext.

```json
{
  "safety": {
    "context_id": "sctx_01",
    "status": "ready",
    "active_dimensions": [
      "identity_context",
      "financial_commitment"
    ],
    "pending_assertions": [],
    "hard_boundary": null
  }
}
```

### 9.4 `WebOperationRequest`

Target extension:

```text
target
operation
arguments
expected_object_version
expected_document_revision
safety
```

### 9.5 No generic `approve=true`

P11 must not introduce a boolean approval flag. Safety state must remain explicit, typed, scoped, expiring, and auditable.

---

## 10. Proposed Schema Model

### 10.1 Principal and identity

```text
SafetyPrincipalRef
  agent_id
  profile_id
  account_owner
```

`account_owner`:

```text
agent_owned
user_owned
shared
unknown
```

### 10.2 Declaration

```text
SafetyDeclaration
  principal
  task
  dimensions[]
  authorization_claim
  origin_scope[]
  expires_at / expires_in_seconds
  max_uses
```

### 10.3 Contract

```text
SafetyContract
  context_id
  template_versions[]
  required_assertions[]
  instruction
  hard_boundaries[]
  status
```

### 10.4 Assertions

```text
SafetyAssertionSet
  context_id
  assertions: map<string, boolean>
  authorization_source
  host_attestation?
```

### 10.5 State

```text
SafetyContextState
  context_id
  principal
  active_dimensions[]
  status
  pending_assertions[]
  expires_at
  remaining_uses
  last_decision
```

### 10.6 Receipt

```text
SafetyReceipt
  receipt_id
  context_id
  agent_id
  profile_id
  origin
  target_object_id
  operation
  p10_effect
  safety_dimensions[]
  assertion_refs[]
  hard_boundary_decision
  final_decision
  before_revision
  after_revision
  result
  timestamp
```

Receipts must never contain passwords, payment secrets, raw card data, tokens, cookies, or unrestricted local paths.

---

## 11. Hard Boundaries

### 11.1 Credential secrecy

The following must never enter Agent-visible state, MCP responses, normal logs, screenshots intended for Agent reading, or error messages:

- password values;
- cookies;
- authorization tokens;
- session storage secrets;
- 2FA seeds and recovery codes;
- payment passwords;
- card verification values;
- bank authentication material;
- private keys.

An Agent may use a bound identity or instrument by reference but cannot retrieve its secret.

### 11.2 Human authentication and verification

The following require Human Takeover:

- password entry for user-owned or protected accounts;
- SMS or authenticator 2FA;
- CAPTCHA;
- biometric verification;
- security-key touch or PIN;
- QR login that requires a user's device;
- account recovery;
- payment challenge, 3-D Secure, bank-app approval, or payment password.

Takeover verifies the human or satisfies an external provider. It is not a repeat interpretation of task authority.

### 11.3 Profile and identity boundary

Each profile carries:

```text
profile_id
owner
bound_agent_ids
allowed_origins
safety_policy_id
financial_policy_id
```

P11 defines and enforces binding metadata. P12 provides full multi-profile and multi-session isolation.

An Agent cannot silently move from an Agent-owned profile to a user-owned profile.

### 11.4 Local resource boundary

Uploads require a `LocalResourceGrant`:

```text
resource_ref
owner
purpose
allowed_origins
expires_at
max_uses
```

Raw local paths are not accepted by the public Agent protocol.

### 11.5 Financial boundary

Each payment instrument and profile may define user-controlled limits:

```text
autonomy_limit
step_up_limit
absolute_limit
daily_limit
monthly_limit
currency rules
transaction types
recurring policy
assurance requirement
```

No global hard-coded definition of “large amount” is used.

### 11.6 Recurring commitment boundary

One-time purchase authority never covers subscriptions, automatic renewal, installments, or recurring donations.

### 11.7 Explicit deny policy

Users may prohibit categories such as:

```text
transfers
cash equivalents
gambling
subscriptions
production deletion
credential creation
external file upload
```

The core architecture supports deny policy without embedding a universal moral or business policy into WebFA.

---

## 12. Payment Instrument Architecture

### 12.1 Product model

WebFA should support protected payment instruments because otherwise an Agent cannot complete low-risk purchases autonomously.

The model is:

```text
Agent chooses an instrument reference
PaymentInstrumentBroker verifies policy
Broker supplies or activates the instrument internally
Agent never receives payment secrets
```

### 12.2 Payment instrument types

Complete target enum:

```text
merchant_saved
system_wallet
tokenized_wallet
issuer_virtual_card
prepaid_card_reference
local_protected_card
```

Recommended order of implementation:

1. merchant-saved payment method;
2. system or tokenized wallet;
3. issuer virtual-card reference;
4. optional local protected card support only after security review.

### 12.3 `PaymentInstrumentRef`

Agent-visible projection:

```json
{
  "instrument_id": "pay_agent_01",
  "owner": "agent",
  "profile_id": "profile-agent-shopping",
  "type": "issuer_virtual_card",
  "brand": "visa",
  "last4": "4821",
  "currency": "CNY",
  "policy_id": "financial-policy-01"
}
```

No full PAN, CVV, payment password, wallet token, or secret credential is returned.

### 12.4 Payment capability

P11 adds a protected semantic capability concept:

```text
provide_payment_instrument
```

It differs from `set_value`:

```text
set_value:
  Agent knows and supplies the value

provide_payment_instrument:
  Agent supplies only an opaque instrument reference
  WebFA or the payment provider supplies protected material internally
```

Card and wallet secret fields must not expose ordinary `set_value` to the Agent.

This may be represented as a protected capability extension rather than a general P10 page-object capability until its exact BrowserHost integration is proven.

### 12.5 Financial policy

```json
{
  "policy_id": "financial-policy-01",
  "currency": "CNY",
  "one_time_purchase": {
    "autonomy_limit": "300.00",
    "step_up_limit": "2000.00",
    "absolute_limit": "10000.00"
  },
  "daily_limit": "1000.00",
  "monthly_limit": "3000.00",
  "subscriptions_allowed": false,
  "transfers_allowed": false,
  "cash_equivalents_allowed": false,
  "minimum_assurance": "runtime_observed"
}
```

### 12.6 Assurance levels

```text
agent_asserted
runtime_observed
provider_verified
user_confirmed
```

Policy may differ by profile and amount.

Example:

```text
Agent-owned low-value card, <= CNY 300:
  agent_asserted is sufficient

User-owned card, <= CNY 300:
  runtime_observed required

Large payment:
  user_confirmed or provider_verified required
```

### 12.7 Financial decision

```text
actual amount <= autonomy limit
and task assertion is valid
and instrument/profile binding matches
and no recurring commitment
and no payment challenge
  -> allow_with_audit

actual amount > autonomy limit
and <= step-up limit
  -> require_step_up

actual amount > absolute limit
  -> deny

payment provider requests verification
  -> require_takeover
```

### 12.8 Card storage decision

The recommended public design is not “store a raw card for the Agent.” It is “bind a protected payment instrument.”

A future local protected-card backend may store only permitted cardholder data in an OS-protected vault and expose it only to an isolated broker. It must never persist card verification values, payment passwords, one-time verification codes, or biometric data.

Initial P11 implementation should not require a raw-card vault. Merchant-saved methods, wallets, and issuer virtual cards are safer and more likely to support autonomous purchases.

### 12.9 User guidance

The user manual must strongly recommend:

- a separate virtual card or prepaid card;
- low limits;
- instant transaction notifications;
- no automatic renewal by default;
- no transfers or cash equivalents;
- not using a primary salary card or high-limit personal credit card.

Documentation does not replace architecture-level limits.

---

## 13. Local Resource Broker

### 13.1 Resource selection

The user or trusted Agent Host registers a file through WebFA UI or a controlled host integration.

```json
{
  "resource_ref": "file_approved_01",
  "display_name": "resume.pdf",
  "owner": "user",
  "purpose": "job_application",
  "allowed_origins": ["https://jobs.example.com"],
  "max_uses": 1
}
```

### 13.2 Agent surface

The Agent sees metadata and the opaque reference, not an unrestricted filesystem location.

### 13.3 Upload execution

The `upload` operation accepts `resource_ref`. The broker resolves the local resource only after verifying:

- current Agent;
- current profile;
- destination origin;
- purpose and expiry;
- remaining use count.

### 13.4 Content inspection

P11 does not require WebFA to semantically inspect file contents. Optional malware scanning or classification may be added later without changing the grant model.

---

## 14. Deterministic Decision Rules

### 14.1 Soft contract decision

```text
No relevant dimension
  -> allow

Relevant dimension, missing assertions
  -> require_assertion

Assertions satisfied, no hard boundary
  -> allow_with_audit
```

### 14.2 Hard-boundary decision

```text
Authentication or payment verification challenge
  -> require_takeover

Financial amount exceeds autonomy threshold but not step-up threshold
  -> require_step_up

Financial amount exceeds absolute limit
  -> deny

Unapproved local resource or destination
  -> deny

Profile ownership mismatch
  -> require_step_up or deny according to policy
```

### 14.3 Missing or uncertain evidence

WebFA must not pretend uncertain evidence is verified.

The policy chooses the required assurance:

```text
agent_asserted accepted
runtime observation required
provider verification required
user confirmation required
```

Unknown evidence is not universally blocked. Agent-owned identities may be configured permissively.

---

## 15. UI Model

P11 UI is primarily a policy and takeover surface, not a constant approval queue.

### 15.1 Agent identity policy

Configure:

- Agent ID;
- bound profiles;
- account ownership;
- allowed origins if desired;
- trust mode;
- default treatment of unknown effects.

### 15.2 Payment instruments

Display only safe metadata:

```text
Visa •••• 4821
Owner: shopping-agent
Autonomy limit: CNY 300
Daily: CNY 279 / 1000
Monthly: CNY 1279 / 3000
Subscriptions: blocked
```

### 15.3 Resource grants

Users select files or directories and grant scoped references.

### 15.4 Step-up card

Used only when scope changes.

Example:

```text
Original autonomous limit: CNY 300
Current total: CNY 329
Request: increase this transaction only to CNY 329
```

### 15.5 Human Takeover

Used for password, 2FA, CAPTCHA, biometric, payment challenge, recovery, and other human-only steps.

### 15.6 Activity and receipts

Show:

- Agent;
- identity/profile;
- origin;
- operation;
- safety dimensions;
- authority source reference;
- hard-boundary result;
- final outcome.

---

## 16. Trust Modes

### 16.1 `trusted_agent`

Default target mode for the user's own trusted Agents.

```text
Agent assertion accepted
Hard boundaries still enforced
No duplicate WebFA approval
```

### 16.2 `host_attested`

Agent Host binds assertions to a conversation/task and protects declaration integrity.

Useful for higher-assurance integrations, but not required for all clients.

### 16.3 `guarded`

Selected dimensions or profiles require WebFA step-up even if the Agent asserts authorization.

Users choose this mode; WebFA does not impose it globally.

---

## 17. Threat Model

P11 addresses:

- webpages attempting to expand authority through prompt injection;
- accidental use of the wrong profile or identity;
- accidental upload of unapproved local files;
- payment beyond a configured limit;
- hidden recurring commitments;
- secret leakage to Agent-visible state;
- Agent operations continuing through a human-only authentication challenge;
- unbounded use of a payment instrument.

P11 does not fully prevent:

- a trusted Agent incorrectly interpreting the user's instruction;
- a malicious Agent lying in self-declared assertions when the user selected `trusted_agent` mode;
- a merchant misrepresenting an item or amount when no reliable Runtime/provider evidence exists;
- fraud or disputes handled by banks, card networks, or merchants;
- all unsafe user-configured policies.

These limitations must be explicit in documentation.

---

## 18. Non-Goals

P11 does not:

- add an LLM to WebFA;
- parse full user conversations;
- maintain per-site purchase or posting scripts;
- judge content quality or social appropriateness;
- provide universal fraud detection;
- bypass authentication, payment verification, CAPTCHA, or platform risk controls;
- expose payment or identity secrets;
- replace P12 multi-profile isolation;
- provide durable task resume;
- introduce site-specific transaction APIs.

---

## 19. Engineering Phases

### P11.0 Definition Freeze

- review and approve this complete target model;
- freeze template dimensions, lifecycle, decision states, protocol integration, and hard-boundary philosophy;
- decide initial trust-mode defaults.

### P11.1 Schema Foundation

Add internal/public schemas for:

- SafetyDimension union;
- SafetyDeclaration;
- SafetyContract;
- SafetyAssertionSet;
- SafetyContextState;
- SafetyDecision;
- SafetyReceipt;
- profile ownership metadata;
- FinancialPolicy;
- PaymentInstrumentRef;
- LocalResourceGrant.

No policy behavior yet.

### P11.2 Template Registry and Contract Compiler

- deterministic versioned template registry;
- localized instructions plus machine-readable assertions;
- composable templates;
- contract tests proving no site-specific flows.

### P11.3 SafetyContext Handshake

- session-scoped SafetyContextManager;
- optional declaration/assertion envelope in `open_url` and `act`;
- WebState safety projection;
- fast path for trusted Agents;
- expiry, max uses, and invalidation.

### P11.4 Runtime Evidence and Mismatch Detection

- map P10 effects to minimum safety dimensions;
- detect upload, protected credentials, identity transitions, and known payment surfaces;
- add missing-dimension responses;
- never infer arbitrary site business semantics.

### P11.5 Credential and Human-Takeover Boundary

- protected-field handling;
- password/2FA/CAPTCHA/biometric/payment-challenge takeover;
- verify that no secrets enter WebState, MCP, logs, receipts, or Agent screenshots.

### P11.6 Local Resource Broker

- opaque resource references;
- origin, purpose, expiry, and use-count restrictions;
- `upload` accepts resource references only;
- Visualizer resource-grant UI.

### P11.7 Identity and Profile Policy

- profile owner metadata;
- Agent/profile binding;
- identity-switch boundary;
- policy UI;
- design remains compatible with full P12 isolation.

### P11.8 Financial Policy and Payment Instrument Contract

- user-defined limits;
- recurring and transfer policies;
- assurance levels;
- PaymentInstrumentRef;
- PaymentInstrumentBroker contract;
- no raw-card storage required.

### P11.9 Payment Backend MVP

Recommended first implementation:

- merchant-saved payment-method selection;
- system/tokenized payment path where available;
- payment challenge takeover;
- amount-policy evaluation when Runtime evidence is available;
- payment receipt without payment secrets.

### P11.10 Step-up UI, Audit, and Final Acceptance

- boundary escalation cards;
- policy pages;
- receipt viewer;
- full real-task regression;
- docs and migration cleanup.

---

## 20. Acceptance Criteria

P11 is accepted only when:

1. WebFA still contains no LLM and does not parse user conversation text.
2. The same generic financial template works across different shopping-site workflows.
3. No site-specific action allowlist is required.
4. A trusted Agent with valid assertions and an in-policy amount can complete a purchase flow without duplicate WebFA approval.
5. Password, 2FA, CAPTCHA, biometric, and payment verification always require Human Takeover.
6. Secrets never enter WebState, MCP responses, logs, receipts, or Agent-readable screenshots.
7. Agent uploads use scoped resource references rather than arbitrary local paths.
8. User-defined autonomy, step-up, absolute, daily, and monthly financial limits are mechanically enforced when the configured assurance level is met.
9. One-time purchase authority cannot authorize recurring commitments.
10. Agent-owned profiles can be configured more permissively than user-owned profiles.
11. Unknown external effects are policy-driven rather than universally denied.
12. Default MCP remains exactly five tools.
13. P10 WebObjects and semantic operations remain the only page-operation model.
14. All safety decisions produce bounded, secret-free receipts.
15. No P11 subphase introduces a disposable public model.

---

## 21. Proposed Defaults for Review

These defaults are proposals, not yet frozen.

### Trusted Agent default

```text
trust_mode = trusted_agent
```

Agent assertions are accepted unless a profile explicitly selects guarded mode.

### Agent-owned profile

```text
external representation -> allow_with_audit
unknown external effect -> allow_with_audit
financial commitment -> assertion + financial policy
recurring commitment -> separate assertion and explicit policy
```

### User-owned profile

```text
external representation -> assertion + audit
unknown external effect -> step-up by default
financial commitment -> assertion + stronger assurance policy
identity switch -> step-up
```

### Payment defaults

```text
subscriptions = disabled
transfers = disabled
cash equivalents = disabled
payment challenge = Human Takeover
autonomy limit = user must configure
```

WebFA should not invent a universal monetary threshold.

### Local resources

```text
public Agent protocol accepts resource_ref only
raw filesystem path is rejected
```

---

## 22. Standards and Design References

P11 is not an OAuth implementation or a payment processor, but several established designs support its architecture:

- OAuth 2.0 Rich Authorization Requests (RFC 9396) demonstrates structured, fine-grained authorization details including type, action, location, amount, and integrity protection: https://www.rfc-editor.org/rfc/rfc9396.html
- W3C Payment Request API models the browser/user agent as an intermediary between merchant, payer, and payment method, with structured transaction totals and payment-method handling: https://www.w3.org/TR/payment-request/
- W3C Secure Payment Confirmation binds authenticated user confirmation to displayed transaction details and produces cryptographic evidence: https://www.w3.org/TR/secure-payment-confirmation/
- WebAuthn keeps user verification and biometric processing inside the authenticator security boundary rather than exposing biometric data to the relying party: https://www.w3.org/TR/webauthn-3/
- PCI DSS and related payment-security requirements reinforce that handling raw cardholder and sensitive authentication data creates a substantially larger security scope. The P11 design therefore prefers references, tokenized methods, wallets, and issuer-managed virtual cards over a raw-card vault.

---

## Decision Summary

P11 should not be an approval wall.

It should be:

```text
Agent Safety Contract
  + Agent self-assertion
  + deterministic hard boundaries
  + protected resource brokers
  + optional scope escalation
  + secret-free audit receipts
```

The governing principle is:

> WebFA tells the Agent what must be confirmed; the Agent evaluates the user context; WebFA records the assertion and enforces only the boundaries it can determine mechanically.

For payments:

> WebFA may use a protected payment instrument on behalf of an Agent, but it must never disclose payment secrets to the Agent.
