# WebFA

**Language**: [中文](https://github.com/FeiZhuLulu/webFA/blob/main/README.md) | English

WebFA is a local **agent-native browser runtime**.

Its goal is not to build a "traditional browser that is easier for agents to operate", but to give agents a native web access interface:

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

WebFA is not a traditional browser UI, not a site-specific API wrapper, and not an autonomous agent.
The agent decides what to do. WebFA opens real websites, keeps local website identities in isolated Profiles, returns structured page state, and performs generic web-object actions.

Status: **Developer Preview**. APIs and behavior may change.

## P10 WebFA Object Model

The default Agent interface now uses the formal **WebFA Object Model** instead of browser-automation primitives:

```text
real web page
  -> WebObjectCompiler
  -> WebState / WebObjects / Capabilities
  -> Agent Semantic Operations
```

The target agent interface is based on web objects, object state, relations, capabilities, versions, and changes. DOM, selectors, coordinates, mouse/keyboard events, CDP, and browser-engine protocols remain Runtime implementation details.

The default MCP surface supports queryable `observe(page/object/query/changes)`, stable object identity, object versions, document revisions, ChangeSets, structured collections/tables/forms, and explicit `opaque_surface` objects with Human Takeover. Legacy `BrowserState` and P7 actions remain only as a default-disabled historical regression layer; without an explicit unsafe opt-in they return `410 legacy_browser_api_disabled`. See `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`.

## What Works Today

- MCP stdio entry point for external agents.
- Five default MCP tools:
  - `webfa.open_url`
  - `webfa.observe`
  - `webfa.act`
  - `webfa.get_tabs`
  - `webfa.switch_tab`
- Managed Chromium runtime path with an isolated Chromium identity directory and BrowserSession per persistent Profile, with no Playwright dependency.
- Agent-readable `WebState` with WebObjects, relations, capabilities, document revisions, ChangeSets, auth status, and takeover state.
- `webfa.act` accepts declared semantic operations only; click/type/press remain internal Runtime strategies.
- Session Monitor projects the same BrowserHost page used by the Agent; after acquiring a time-bounded, Session-scoped `HumanControlLease`, the user can complete login, QR, verification, 2FA, and authorization on that page.
- Connection-scoped Profile Grants and SessionLeases ensure that at most one agent writes to a Profile at a time, while different Profiles can run concurrently.
- An optional lightweight WebFA Runtime Manager for Runtime status, external Agent/Session state, page projection, Profile Bootstrap, Safety Center, Step-up, and safety receipts. It does not run an Agent. Visualizer, Profile, Provider credential administration, and human approval decisions use a separate high-entropy local control token and are isolated from Agent REST/MCP calls; Agents may still poll approval state.
- P11 safety enforcement for task-scoped SafetyContext, Runtime evidence elevation, Profile/Origin binding, exact single-use Step-up, credential takeover, resource grants, and financial policy.

## Current Limits

- Control Center and Session Monitor are inspection, management, and constrained-takeover surfaces, not a complete desktop browser. Login and QR flows should use HumanControl in the target Session Monitor.
- A persistent Profile can have at most one writable BrowserSession at a time; different Profiles can run concurrently.
- WebFA does not bypass anti-bot, CAPTCHA, risk-control, or platform safety systems.
- Active Monitor/Profile Grants, task traces, and resumable execution state do not survive a Runtime restart; old Sessions become `interrupted`. Durable Trace / Resume belongs to the deferred P13 phase.
- `open_url` and link navigation are still modeled as navigation. If a site abuses GET navigation to perform an external write, Runtime cannot determine that business side effect from protocol semantics alone; this remains a documented boundary.
- Some historical transaction/provider code remains in the repository as legacy code. Primitive BrowserAction REST is disabled by default and is not exposed through MCP.

## Install

### Source installation (recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

Run a local self-test:

```powershell
webfa doctor
```

Start the Runtime manually:

```powershell
webfa-runtime
```

Run the MCP stdio server:

```powershell
webfa-mcp
```

`webfa-mcp` reuses an already-running Runtime whose identity matches. It auto-starts a Runtime only when `WEBFA_RUNTIME_URL` is a loopback HTTP address and the endpoint is unreachable. A cross-process endpoint lock coalesces concurrent starts, and each MCP client holds its own lease. When the last client exits, it stops only a Runtime owned by MCP auto-start; it never stops a Desktop-owned or externally started Runtime.

To develop the optional human control surface, install the Node dependencies and start the Visualizer (Renderer + Electron; Electron generates the control token and starts Runtime):

```powershell
npm install
npm run dev
```

`npm run dev:renderer` starts only the static Renderer and does not receive a securely injected Visualizer control token, so it is not a complete control plane.

Default URL:

```text
http://127.0.0.1:8788
```

### Optional Windows x64 Runtime Manager preview

The repository can produce a Windows x64 developer preview. It is only a local host and human management surface for WebFA Runtime: it starts Runtime, shows external Agent/Session state, generates MCP client configuration, and provides monitoring, approval, and HumanControl. It contains no model, planner, task loop, or built-in Agent. Every external Agent still starts and owns its own MCP stdio connection.

The preview bundles a PyInstaller `onedir` sidecar, so Python is not required on the target machine; local Chrome or Edge is still required. It is not a prerequisite for publishing the open-source Runtime source/wheel and is not yet a formal Windows product. See `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md` and `RELEASE_CHECKLIST.md` for packaging evidence and any future desktop-release gates.

## Configure an Agent

Generate a standard MCP config:

```powershell
webfa mcp-config --agent-id codex
```

Generate an opencode config:

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

Each agent should use a distinct `WEBFA_AGENT_ID`. Write authority is not a global single-agent lock: a Profile can have only one writable BrowserSession at a time, and writes within that Session are protected by an exclusive Agent Lease. Other agents can still observe and will see the current lease in `WebState` and `/health`. Sessions on different Profiles can be run concurrently by different agents.

Integration docs:

- `docs/agent-integrations/opencode.md`
- `docs/agent-integrations/kimi-code.md`
- `docs/agent-integrations/claude-code.md`
- `docs/agent-integrations/codex.md`

## Login

Preload a login session for the default WebFA profile:

```powershell
webfa login github
webfa login --url https://example.com/login
```

Developer Preview uses Session Monitor's projection of the same BrowserHost page as the primary takeover path. Agents should not type passwords, verification codes, or 2FA codes. When a page enters a login, QR-code, verification-code, 2FA, or authorization flow, the user acquires a time-bounded `HumanControlLease` in that Session's Monitor and operates the same page directly. While page keyboard capture is focused, Escape returns to the Monitor's Page Keyboard button without releasing the lease; Enter re-enters capture, or Tab reaches Return to Agent. Only Agent writes in that Session pause during takeover; after release, expiry, revocation, or disconnect, the Agent performs a fresh `webfa.observe` before continuing.

`webfa login` remains as a protected manual pre-login helper. The former duplicate-page Electron AuthSurface is permanently retired: it does not close or restart BrowserHost and does not create a second page. `WEBFA_AUTH_SURFACE_MODE=legacy` remains only for historical compatibility and is not the packaged Desktop authentication path.

## Environment

Copy `.env.example` for local notes if needed. Common variables:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"  # the only supported BrowserHost path
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"  # legacy visible-host compatibility only
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
# A standalone Runtime must receive an explicit high-entropy value before its local human control plane can be used (the historical variable name remains):
$env:WEBFA_VISUALIZER_CONTROL_TOKEN="<random-secret>"
# Historical regression only; never enable in production:
# $env:WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API="1"
```

`WEBFA_AGENT_LEASE_TTL_SECONDS` also controls the P12 connection-exclusive
Session Lease. Every successful five-tool call renews a still-active connection
lease; a read-only call never resurrects an expired lease.

For source runs and standalone CLI use, an unset `WEBFA_HOME` defaults to `%APPDATA%\WebFA` on Windows.

The variables above are for source runs, standalone CLI use, and development. The packaged Desktop does not pass arbitrary parent-process `WEBFA_*` configuration through to its sidecar: it inherits only a strict operating-system environment allowlist, validates that the API host is loopback, and forces the sidecar's `WEBFA_HOME` to Electron `app.getPath("userData")`, so an inherited `WEBFA_HOME` cannot redirect packaged Profile/Session data. It also injects the exact Runtime URL, version/instance identity, and browser mode. Every owned Runtime start receives a fresh high-entropy local control token, while Console and Monitor origins are bound exactly to that run's local Renderer origin; packaged mode ignores an externally supplied fixed control token and development Renderer URL. The token is sent as `X-WebFA-Visualizer-Token`, is used only by the human control plane, and is never included in an Agent's MCP configuration. OpenAPI represents these operations with the `VisualizerControlToken` API-key security scheme; ordinary Agent Runtime operations neither declare nor receive it.

## Local Development

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

## Safety Contract

WebFA should not expose these to agents by default:

- cookies
- localStorage / sessionStorage values
- tokens or authorization headers
- password values
- raw Playwright
- raw CDP
- selector / XPath / evaluate escape hatches
- full DOM / HTML

Default MCP tools must remain exactly the five browser tools. Legacy transaction MCP tools appear only when explicitly enabled:

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

## Roadmap

See `docs/browser-runtime-roadmap.md`.

See `docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md` for the current mapping from phase status to live implementation and maintained gates. Read `docs/reports/README.md` before using historical reports: they are point-in-time engineering evidence and do not automatically certify a new release candidate.

Current milestone: P10 WebFA Object Model, P11 Agent Safety Contract, P12 Multi Session / Multi Profile Core, and Post-Core Profile Bootstrap are complete. P12 provides a persistent Profile Catalog, isolated Chromium Hosts and cross-process locks, BrowserSessionRuntime, concurrent multi-Profile SessionManager/Supervisor routing, connection-scoped Profile grants, Session-exclusive Agent leases, global Tab/WebObject routing, five-tool `profile_ref` integration, Session-specific Monitor grants, VisualStreamHub, independent HumanControl isolation, and explicit connection/Profile/Session/generation binding for SafetyContext, Step-up, local resources, payment authority, and SafetyReceipt. Profile Bootstrap includes human login, Cookie import, identity-scoped Profile clone, and Scrypt + AES-256-GCM encrypted `.webfa-profile` Bundles. Clone and Bundle transfer Default-profile website identity while excluding history, bookmarks, password/autofill databases, open tabs, extensions, and other Chrome subprofiles. Restore reports browser storage restoration only and never promises login recovery. All Bootstrap capabilities remain on the protected local control plane and never enter MCP, WebState, Monitor, or SafetyReceipt. See `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md` and `docs/reports/PROFILE_BOOTSTRAP_ADVERSARIAL_REVIEW.md`.

Current work: P13 is deferred while P1–P12 and Post-Core Profile Bootstrap undergo systematic closure, maintenance, and adversarial review. The Control Center and Session Monitor will continue to improve in visual quality, usability, accessibility, and responsive behavior.

Deferred future work:

- P13 Durable Trace / Resume

## License

MIT. See `LICENSE`.
