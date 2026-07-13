# WebFA Runtime Roadmap

WebFA is a local, plugin-first agent browser runtime.

The long-term product surface is the agent interface: open URLs, observe
agent-readable page state, and perform generic web-object operations. Desktop UI
is optional observability and takeover surface.

## Runtime Layers

WebFA should keep these layers separate:

```text
Agent Interface
  MCP / REST / Console calls: open_url, observe, act, tabs

WebFA Browser Runtime
  sessions, WebState, WebObject identity, semantic operations, safety contracts

Web Object Layer
  RawWebSnapshot -> WebObjectCompiler -> ObjectRegistry -> ChangeSet

Browser Host
  managed Chromium as the formal implementation path
  future BrowserHost implementations must preserve the Web Object contract

Browser Engine
  runs real HTML, CSS, JavaScript, storage, cookies, and web APIs
```

WebFA uses browser engines and host protocols as implementation details. Its
product surface should be agent-native web operations: URL navigation, readable
page objects, forms, links, controls, lists, and safe object-level actions.

## Roadmap

```text
P4/P4.5
  Agent browser validation.
  Proved the first open_url -> observe -> act -> observe loop.

P5
  Browser Runtime Core.
  Keep public WebFA APIs unchanged.
  Isolate browser host control behind driver boundaries.
  Generate BrowserState through AgentViewBuilder.
  Track current-page element ids through ElementRegistry.
  Keep one default BrowserSession/Profile.

P5.5
  Content Blocks MVP.
  Goal: BrowserState.content_blocks stops being empty; agents get a more stable
  reading structure than one flat visible_text blob.
  Route: RawPageSnapshot -> raw content block candidates -> AgentViewBuilder ->
  BrowserState.content_blocks, each block carrying {id, type, text, element_ids}.
  Collect generic DOM blocks (h1/h2/h3, p, li, article, form, nav, role=listitem),
  cap text length and count, bind nearby data-webfa-id element ids.
  Public MCP/REST tools are unchanged. No HTML, no DOM path, no site rules,
  no LLM summaries, no suggested actions, no Visualizer, no new MCP tools.
  Status: done — BrowserContentBlock schema, AgentViewBuilder mapping, observe
  script collection, search-results integration test, security contract.

P6
  Managed Chromium BrowserHost Closed Loop.
  Keep Chromium/Blink/V8 as the web engine and validate WebFA-managed browser
  host control outside a human-browser product surface.
  Add a BrowserHost layer under BrowserDriver. The first experimental host is
  ManagedChromiumHost, which launches a WebFA-managed Chromium process and uses
  an internal CDP channel for navigate/evaluate/actions.
  Status: done — host contract, shared observe probe, managed Chromium
  open/observe/tabs/close, and minimal type/click/press/clear/wait closed loop.

P7
  Agent-Native Web Operations.
  Move beyond low-level click/type as the primary abstraction. Improve
  BrowserState and action semantics around generic web objects: URL affordances,
  forms, links, controls, lists, and content blocks.
  Implement fill_form, submit_form, follow_link, activate_control,
  choose_option, read_list, and inspect_block. These are generic webpage
  operations, not site-specific APIs and not LLM suggestions.
  Existing click/type/press remain as fallback primitives.
  Keep the five default MCP browser tools; page operations stay under
  webfa.act.
  Historical P7 state: managed-chromium became the default while a temporary
  fallback still existed. P10.9 removes that fallback and its dependency.
  /health reports safe browser status without exposing cookies, storage,
  tokens, or internal debug endpoints.
  Complex validation: passed GitHub login persistence, authenticated
  navigation, safe pre-submit form filling, Wikipedia/MDN/Hugging Face reading,
  and GitHub safety-stop checks. npmjs.com tests were blocked by Cloudflare
  headless protection; P7 records this as an external anti-bot limitation, not
  a WebFA object-operation failure.

P8
  Plugin-first Packaging / Agent Entry Package.
  Make WebFA easy for external agents to install and use through MCP/local
  plugin/CLI entry points. Desktop remains optional.
  Provide webfa-runtime, webfa-mcp, and webfa helper commands. webfa-mcp can
  reuse or auto-start a local Runtime, and webfa doctor provides a local smoke
  test before external agent validation.
  Status: Kimi Code CLI external MCP validation passed, including real website
  reading, GitHub unstar, and public repository creation. Follow-up runtime
  quality work should improve React controlled input event compatibility.
  Future non-page resource tool categories may include sessions/profiles,
  downloads/uploads, permissions, approvals/confirmations, and diagnostics/traces.
  Do not name or ship those tools until their resource domain is implemented.

P8.5
  Login/Profile Onboarding.
  Add a lightweight CLI entry for user-assisted login before packaging:
  webfa login github and webfa login --url <login-url>.
  The command opens a visible WebFA-managed Chromium window with the default
  managed-chromium profile. The human signs in manually, including password,
  QR code, 2FA, or authorization prompts; WebFA closes the window after the
  user confirms in the CLI and keeps the profile for future agent sessions.
  This does not add MCP tools, does not ask agents to type credentials, and
  does not expose cookies, storage, passwords, or tokens.

P8.6
  Automatic Auth Takeover UI.
  Move login handling into the Runtime path: when open_url or act lands on a
  login, QR-code, verification-code, 2FA, or authorization surface, WebFA marks
  BrowserState.auth and routes the user to the WebFA takeover surface using the
  same default profile.
  The user completes password, QR, verification, or approval steps manually.
  Agents continue with observe and never receive credentials, cookies, storage,
  password values, tokens, or new login-specific MCP tools.

P8.7
  Runtime Stability and Post-Login Usability.
  Fix the first real auth validation findings: reduce auth false positives on
  logged-in pages, keep the CDP connection stable with reconnect behavior,
  improve React-style controlled input filling, expose generic row/list items
  as addressable elements, and add double_click for legacy row UIs such as mail
  inboxes.
  This does not add anti-detect behavior or site-specific parsers; site risk
  blocks remain external platform behavior.

P8.8
  Agent Integration Hardening.
  Make external agent usage safer without adding browser features. Each MCP
  client should set WEBFA_AGENT_ID. Runtime tracks one active agent lease for
  browser-changing operations, while observe/tabs/health remain readable and
  show the active agent. The default profile remains shared, so all agents
  connected to the same Runtime use the same website login state. This phase
  also records opencode, Kimi Code, Claude Code, and Codex setup docs.

P8.10
  Visible Host Stability.
  Stabilize host lifecycle and define browser_host_closed recovery semantics.
  This phase is retained as a lifecycle milestone; the product direction after
  P9.1 is WebFA-owned takeover, not a separate always-visible Chromium host.

P8.11
  Developer Preview Release Hardening.
  Keep the current WebFA capability set fixed and prepare the repository for a
  public developer-preview release. Verify clean install, MCP entry package,
  docs consistency, legacy isolation, local proxy-safe Runtime calls, ignored
  scratch files, and release checklist coverage.

P9
  WebFA Visualizer.
  Show WebFA's own runtime state: URL, title, BrowserState,
  content_blocks, elements, screenshots, action log, and takeover controls.
  Keep it focused on observation and takeover, not general human browsing.
  Status: implemented as MVP — /v1/visualizer/state, local preview cache,
  action log, host restart/open controls, and Electron/Next three-column
  inspector UI. Element highlight overlay and productized tab switching are
  intentionally left for follow-up work.

P9.1
  WebFA-owned Auth Surface.
  Login, QR-code, verification-code, 2FA, and authorization flows happen inside
  the WebFA UI takeover area. Opening the takeover area closes the hidden
  Runtime host to release the shared default profile; completing takeover
  destroys the embedded WebContents and restarts the hidden host with the same
  profile. Separate visible Chromium hosts remain legacy fallback only.

P9.2
  Runtime Safety + Page Surface Hardening (Developer Preview).
  Add URL safety policy (`WEBFA_PRIVATE_URL_POLICY`), structured runtime errors
  with `recover_hint`, JavaScript dialog MVP (`accept_dialog` / `dismiss_dialog`
  through `webfa.act`), same-origin iframe frame metadata, and Agent View
  hardening for security/dialog/frame fields. Managed Chromium is the complete
  implementation path for P9.2; Playwright remains an explicit fallback driver
  for basic open/observe/act only — dialog, frame, and URL-policy behaviors are
  not required to match on Playwright. MCP tool count stays at five.
  Scope note: this phase improves agent-facing safety contracts; it is not
  production-grade network isolation (no DNS-aware SSRF blocking yet).
  Follow-up: DNS/IP literal hardening, tighten managed-chromium CDP origins,
  `prompt` text input for `accept_dialog`.

P10
  WebFA Object Model.
  Upgrade the runtime from DOM-like elements and a global action enum to
  WebState, WebObjects, object capabilities, semantic operations, stable object
  identity, object versions, document revisions, and compact ChangeSets.
  Add queryable observe modes (page, object, query, changes), structured
  document/collection/table/form/dialog/frame reading, and explicit
  opaque_surface objects for regions that WebFA cannot reliably compile.
  Agent-facing click/type/press are removed from the formal target protocol;
  low-level browser events remain internal execution strategies only.
  Managed Chromium becomes the only formal BrowserHost path and the Playwright
  fallback is removed during P10 migration.
  Status: complete. P10.0-P10.9 deliver WebState, stable WebObjects, queryable
  observe, object versions, document revisions, ChangeSets, structured reading,
  capability-driven semantic operations, opaque surfaces, generalized takeover,
  and the public five-tool MCP migration. Managed Chromium is the only supported
  BrowserHost path and the Python package has no Playwright dependency.
  BrowserState/BrowserAction compatibility is isolated under the explicit
  `/v1/browser/legacy/*` REST namespace; hidden old URL aliases remain for one
  compatibility cycle, are absent from OpenAPI, and are not used by MCP.
  Full design: docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md.

P11
  Agent Safety Contract and Hard Boundaries.
  Keep user-intent interpretation in the Agent layer. WebFA deterministically
  returns composable safety templates, accepts task-scoped Agent assertions,
  and enforces only mechanical boundaries such as credential secrecy, human
  authentication/payment takeover, profile binding, scoped local resources,
  recurring commitments, protected payment instruments, and user-defined
  financial limits. The normal trusted-Agent path is allow-with-audit rather
  than duplicate WebFA approval. No site-specific operation allowlists and no
  additional default MCP tools.
  Status: complete. P11.0-P11.10 are implemented and accepted. Safety schema,
  versioned templates, task-scoped SafetyContext, Runtime evidence/mismatch
  detection, protected credential takeover, LocalResourceBroker, Profile policy,
  user-defined financial limits, opaque PaymentInstrumentBroker, exact-scope
  single-use step-up grants, Visualizer Safety Center, and bounded secret-free
  SafetyReceipt audit are live. Real Managed Chromium validation covers external-
  write preflight, user-owned identity escalation, protected upload, payment
  verification takeover, Runtime-observed totals, autonomous saved-method payment,
  and approved over-autonomy payment scope escalation. P12 Multi Session / Multi
  Profile is next. Detailed plan: docs/p11plan.md. Final acceptance:
  docs/reports/P11_FINAL_ACCEPTANCE_REPORT.md. The earlier design draft remains at
  docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md for design history.

UI-1B
  Session Monitor Projection Architecture.
  Keep BrowserHost as the only real page instance and make the Monitor a
  structured Runtime and visual-surface projection. The Monitor never loads the
  target URL or exposes Chrome UI. Phases 1-6 are complete: SessionEventBus,
  replaceable VisualSurfaceProvider, same-target ManagedChromium screencast,
  short-lived Session-scoped MonitorGateway, local JSON/binary WebSocket
  multiplexing, a separate limited Electron Monitor window, bound Canvas frame
  rendering, and an exclusive time-bounded HumanControlLease. The Canvas remains
  read-only except while the local user holds that lease; mouse, keyboard, wheel,
  paste, and composition events are then forwarded to the same BrowserHost page.
  Agent writes pause, protected observe remains available, and release,
  disconnect, revoke, or expiry restores Runtime control. The duplicate-page
  Electron AuthSurface is permanently retired. No Agent REST or MCP capability
  was added. Frozen design: docs/ui/UI1B_MONITOR_PROJECTION_ARCHITECTURE.md.
  Phase 4-5 report: docs/reports/UI1B_MONITOR_PROJECTION_PHASE_4_5_REPORT.md.
  Phase 6 report: docs/reports/UI1B_HUMAN_CONTROL_PHASE_6_REPORT.md.
  Post-implementation maintenance review:
  docs/reports/UI1B_PHASE_6_MAINTENANCE_REVIEW.md.

P12
  Multi Session / Multi Profile.
  Frozen target architecture: persistent BrowserProfile identity containers,
  dedicated per-active-Profile user-data-dir and Managed Chromium Host, at most
  one active writable BrowserSession per Profile, multiple Tabs per Session,
  concurrent execution across different Profiles, BrowserRuntimeSupervisor,
  connection-scoped Profile grants, Session-exclusive Agent leases, globally
  routed opaque Tab/WebObject identities, per-Session Monitor/HumanControl
  isolation, and fail-closed generation binding for P11 authority. The default
  Agent MCP surface remains exactly five tools. Cookie import is a protected
  Profile Bootstrap consumer after P12 Core, not an Agent tool or a prerequisite
  for Core acceptance. P12.1-P12.3 are complete: persistent Profile Catalog,
  Profile-local P11 policy, explicit ProfileLaunchSpec, OS-backed process lock,
  legacy default storage migration, real Chromium storage isolation,
  BrowserSessionRuntime extraction, and persistent Session lifecycle are
  implemented. P12.4-P12.6 are also complete: concurrent multi-Profile
  SessionManager/Supervisor routing, connection-scoped Profile grants,
  Session-exclusive Agent leases, globally routed opaque Tab and WebObject IDs,
  optional open_url profile_ref integration while preserving exactly five MCP
  tools, Session-bound Monitor grants, multi-consumer VisualStreamHub, and
  independent HumanControl isolation. P12.7 is complete: SafetyContext,
  Step-up, LocalResource, payment authorization, selected-payment state, and
  SafetyReceipt authority are now explicitly bound to trusted Agent connection,
  Profile, Session, and Runtime generation scopes, with origin/document/object
  bindings where applicable. P12.8 final acceptance and migration review is
  complete. Real Chromium verifies concurrent persistent Profile isolation for
  Cookie, localStorage, IndexedDB, and Service Worker registration, and the
  legacy manual-login helper now uses the canonical Profile path and process
  lock. P12 Core is accepted.
  Frozen design: docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md. Reports:
  docs/reports/P12_1_3_PROFILE_SESSION_FOUNDATION_REPORT.md,
  docs/reports/P12_4_6_MULTI_SESSION_ROUTING_MONITOR_REPORT.md,
  docs/reports/P12_7_P11_AUTHORITY_RESCOPING_SECURITY_REVIEW.md, and
  docs/reports/P12_8_CORE_FINAL_ACCEPTANCE_MAINTENANCE_REVIEW.md.

Profile Bootstrap
  Post-Core protected Profile maintenance. Cookie import and Profile clone are
  complete. Cookie import provides local JSON/Netscape input, redacted two-phase
  preview, a bounded ProfileMaintenanceHost, CDP Storage.setCookies, and real
  Chromium persistence validation. Clone provides cold source snapshots,
  ProfileMutationLease on source and generated target, safe filesystem copying,
  runtime-artifact exclusion, atomic target registration, cleanup on conflict,
  and real Chromium identity transfer plus post-clone isolation. Neither feature
  enters MCP, WebState, Monitor, receipts, or Agent authority. Remaining work:
  WebFA Profile Bundle export/restore. Reports:
  docs/reports/PROFILE_BOOTSTRAP_COOKIE_IMPORT_REPORT.md and
  docs/reports/PROFILE_BOOTSTRAP_CLONE_REPORT.md.

P13
  Durable Trace / Resume.
  Persist semantic operations, WebState revisions, object versions, ChangeSets,
  takeover and approval events, and bounded artifacts so interrupted agent tasks
  can be inspected and resumed.

Long term
  Keep mature web engines such as Chromium/Blink/V8 as implementation details.
  Keep WebFA centered on agent-readable WebObjects, semantic operations, and
  explicit capability and safety contracts.
```

## Constraints

WebFA should not expose raw browser-control protocols, selectors, XPath, or site-specific API wrappers as the main agent interface.

The browser engine may remain Chromium/Blink/V8 or another real web engine. The goal is to provide an agent-native web runtime, not to reimplement the modern web engine from scratch.
