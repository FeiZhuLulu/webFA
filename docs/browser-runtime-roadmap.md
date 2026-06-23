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
  sessions, page_state, element ids, agent-native web operations, safety contracts

Browser Driver
  stable fallback driver
  managed Chromium host driver
  future BrowserHost implementations

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
  Engineering finish: managed-chromium is the default runtime path; Playwright
  remains only as an explicit fallback via WEBFA_BROWSER_DRIVER=playwright.
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
  BrowserState.auth and automatically relaunches the current managed Chromium
  page as a visible window using the same default profile.
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
  Default developer preview to visible managed Chromium so login, QR, 2FA, and
  human takeover happen in one stable host. Auth takeover only relaunches when
  Runtime is explicitly headless.
  If the visible host window is closed, observe/act/tabs/switch_tab return
  browser_host_closed. open_url restarts the host under the same default
  session/profile, clears ElementRegistry, and invalidates old element ids.

P9
  WebFA Visualizer.
  Show WebFA's own runtime state: URL, title, BrowserState, content_blocks, elements, screenshots, highlights, action log, and takeover controls.
  Keep it focused on observation and takeover, not general human browsing.

P10
  Element Registry v2.
  Reduce dependence on data-webfa-id injection with role/name/text/tag/dom_path/bbox/nearby_text hints.

P11
  Multi Session / Multi Profile.
  Expose session_id/profile_id only after default session is stable.

P12
  Real Task Safety Layer.
  Add human confirmation before final high-risk writes such as send, create, delete, purchase, publish, or settings changes.

Long term
  Keep mature web engines such as Chromium/Blink/V8 where useful.
  Keep WebFA centered on agent-readable state, URL-native navigation, and
  generic web-object operations.
```

## Constraints

WebFA should not expose raw browser-control protocols, selectors, XPath, or site-specific API wrappers as the main agent interface.

The browser engine may remain Chromium/Blink/V8 or another real web engine. The goal is to provide an agent-native web runtime, not to reimplement the modern web engine from scratch.
