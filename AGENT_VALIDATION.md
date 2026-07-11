# WebFA Agent Validation Harness

This harness validates the current P10 public Agent surface plus the complete P11.1-P11.10 Safety Contract, Runtime evidence, protected takeover, LocalResourceBroker, Profile policy, PaymentInstrumentBroker, exact-scope step-up, and SafetyReceipt audit:

```text
WebState + stable WebObjects + queryable observe + declared capabilities + semantic operations
+ SafetyDeclaration + SafetyContract + AgentAssertions + SafetyContext
+ RuntimeEvidence + protected takeover + opaque resource_ref upload
+ Profile ownership/binding + FinancialPolicy + provide_payment_instrument
+ exact-scope StepUpRequest + secret-free SafetyReceipt
```

Agents should read `AGENT_MANUAL.md` before validation. WebFA is not a Playwright wrapper, a selector API, a screenshot-coordinate controller, a site API wrapper, or an autonomous agent.

The public loop remains:

```text
external agent / MCP client
  -> webfa.open_url
  -> webfa.observe
  -> webfa.act
  -> webfa.observe
```

## Required Runtime Setup

Install project dependencies and ensure Google Chrome, Microsoft Edge, or another supported Chromium executable is installed:

```powershell
pip install -e ".[dev]"
npm install
webfa doctor
```

Set `WEBFA_CHROMIUM_EXECUTABLE` only when WebFA cannot discover a system Chromium installation.

Start the desktop stack:

```powershell
npm run dev
```

Or start only Runtime:

```powershell
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787
```

The MCP server is started by the MCP client with:

```powershell
python -m apps.runtime.mcp.server
```

Use this environment variable when the MCP client connects to a separately running Runtime:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
```

## Expected MCP Tools

By default the agent sees exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

The agent must not see or send:

```text
click / double_click / type / press / focus
selector / XPath / locator
raw DOM / full HTML
evaluate / raw CDP / Playwright
cookies / storage / tokens / password values
site-specific business tools
```

Legacy transaction tools appear only when explicitly enabled with `WEBFA_ENABLE_LEGACY_TRANSACTION=1`; they are not part of browser validation.

## Level 0: REST WebObject Loop

Use:

```text
tests/fixtures/agent_validation_page.html
```

Expected flow:

```text
POST /v1/browser/web/open
POST /v1/browser/web/observe  { mode: "query", query: { capability: "set_value" } }
POST /v1/browser/web/act      { operation: "set_value", target: "obj_*", arguments: { value: "Fei" } }
POST /v1/browser/web/observe  { mode: "query", query: { role: "form" } }
POST /v1/browser/web/act      { operation: "submit", target: "obj_*" }
POST /v1/browser/web/observe  { mode: "query", query: { text_contains: "Hello Fei" } }
```

Automated test:

```powershell
pytest tests/integration/test_web_object_api.py -q
```

## Level 1: MCP Stdio WebObject Loop

Automated test:

```powershell
pytest tests/integration/test_mcp_stdio_browser.py -q
```

The test starts a real Runtime and MCP stdio server, verifies the five-tool schema, and runs:

```text
webfa.open_url
webfa.observe(query)
webfa.act(set_value)
webfa.observe(query)
webfa.act(submit)
webfa.observe(query)
```

It also verifies dialog recovery:

```text
webfa.act(activate)
  -> dialog_required
webfa.observe(query role=dialog)
webfa.act(dismiss)
webfa.observe(query)
```

## Level 1.5: SafetyContext Handshake

Automated coverage is included in:

```powershell
pytest tests/integration/test_web_object_api.py::test_public_web_object_rest_safety_handshake -q
```

Expected flow:

```text
webfa.open_url(safety.declaration)
  -> safety_decision=require_assertion
  -> WebState.safety.status=assertion_required

webfa.act(safety.context_id only)
  -> ok=false
  -> executed=false

webfa.act(safety.context_id + assertions)
  -> safety_decision=allow_with_audit
  -> semantic operation executes
  -> configured context use is consumed
```

Validation must also confirm that `webfa.open_url` and `webfa.act` expose optional `safety` fields while the default tool list remains exactly five tools.

## Level 1.6: Runtime Evidence and External Mutation

Automated coverage:

```powershell
pytest tests/integration/test_web_object_api.py::test_runtime_evidence_requires_context_for_external_submit_then_allows_agent_owned_unknown_effect -q
```

Expected flow on an HTTP(S) form:

```text
submit without safety
  -> require_assertion
  -> status=undeclared
  -> executed=false

submit with Agent-owned trusted unknown_external_effect declaration
  -> allow_with_audit
  -> executed=true
```

The test must use one generic Safety dimension across the site flow; it must not use a site-specific allowlist.

## Level 1.7: Protected Inputs and Local Resource Upload

Use:

```text
tests/fixtures/p11_safety_page.html
```

Automated coverage:

```powershell
pytest tests/integration/test_visualizer_api.py::test_protected_payment_field_requests_payment_verification_takeover -q
pytest tests/integration/test_visualizer_api.py::test_visualizer_resource_grant_and_real_upload -q
```

Validate:

```text
card/payment field -> request_human_takeover -> payment_verification
password/OTP/card/CVV values absent from Agent-visible state
file chosen through Visualizer -> opaque resource_ref
upload requires local_data_egress SafetyContext
Agent/Profile/Origin/purpose checks pass
real input[type=file] receives the approved display filename
resource use count is consumed
no local path appears in REST, MCP, Visualizer, logs, or evidence
```

## Level 1.8: Profile Policy and Protected Payment

Automated coverage:

```powershell
pytest tests/integration/test_web_object_api.py::test_user_owned_identity_switch_requires_profile_step_up -q
pytest tests/integration/test_web_object_api.py::test_payment_instrument_broker_enforces_runtime_amount_and_completes_saved_method_flow -q
```

Validate:

```text
Profile owner/trust mode is visible to the Agent
Agent/Profile/Origin binding mismatch -> deny
user-owned switch_account -> require_step_up -> executed=false
saved payment method -> provide_payment_instrument only
Runtime observes Order total near a conservative total marker
amount/currency mismatch -> deny
within user autonomy limit -> allow_with_audit
above autonomy limit -> require_step_up
payment response exposes brand/last4 only
SafetyReceipt contains no instrument secret
raw card/3DS/payment password remains Human Takeover
```

The merchant-saved test uses a generic financial SafetyContext and FinancialPolicy. It must not rely on a site-specific purchase allowlist.

## Level 1.9: Step-up UI and Safety Receipts

Automated coverage:

```powershell
pytest tests/integration/test_web_object_api.py::test_payment_step_up_ui_approval_is_exact_scope_single_use_and_audited -q
pytest tests/unit/test_step_up.py tests/unit/test_safety_audit.py -q
```

Expected flow:

```text
payment amount > autonomy_limit and <= step_up_limit
  -> require_step_up
  -> executed=false
  -> pending exact-scope step_up_id
  -> secret-free not_executed receipt

Visualizer approves only this request
Agent retries the same operation with context_id + step_up_id
  -> exact binding and scope verified
  -> allow_with_audit
  -> operation executes once
  -> step-up becomes consumed
  -> secret-free executed receipt
```

Validate that changing Agent, Profile, Origin, target, operation, amount, currency, or reusing a consumed step-up is rejected. The Visualizer state and receipt endpoints must not expose PAN, CVV, OTP, wallet token, password, cookies, or local absolute paths.

## Level 2: External Agent Local Page

Recommended prompt:

```text
Use WebFA as your browser. Open the local validation page at <file-url>.
Find the field WebObject that declares set_value, set it to "Fei", find the form
that declares submit, submit it, then query for the result text.
Use only webfa.open_url, webfa.observe, and webfa.act.
Do not use click, type, press, selectors, coordinates, raw DOM, Playwright, CDP,
or site-specific APIs.
```

Pass condition:

```text
The agent reports "Hello Fei" from a WebObject returned by observe.
```

## Level 3: Structured Public Pages

Validate low-risk public pages such as:

```text
documentation pages
public repository search
public model search
articles
lists and tables
basic forms
```

The Agent should use:

- page mode for document overview;
- query mode to locate objects by role, name, capability, origin, or text;
- object mode for relations and range reads;
- changes mode after dynamic updates.

Do not perform account writes at this level.

## Level 4: Human Takeover and Persistent Profile

Manual flow:

```text
1. Open a site that requires authentication.
2. Observe authentication or request Human Takeover.
3. User completes login in the WebFA takeover surface.
4. Complete takeover and resume with observe.
5. Restart Runtime.
6. Open the site again and confirm profile state persists.
```

Also validate an opaque fixture:

```text
tests/fixtures/opaque_surface_page.html
```

Expected result:

```text
canvas -> opaque_surface -> request_human_takeover
```

WebFA must not fall back to screenshot-coordinate control.

## Level 5: Real Task Preflight

Use realistic pages but stop before irreversible final effects. For example:

```text
Open a repository creation form.
Set fields through semantic operations.
Inspect the final form state.
Stop before the final external write unless the safety layer explicitly approves it.
```

## Acceptance Gate

Run:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

The public MCP test must prove:

```text
open_url -> observe WebObjects -> semantic act -> observe changes
```

No default Agent-facing request or response may require browser primitives, selectors, raw DOM, Playwright, or CDP.
