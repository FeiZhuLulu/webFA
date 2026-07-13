# WebFA

**Language**: [中文](README.md) | English

WebFA is a local **agent-native browser runtime**.

Its goal is not to build a "traditional browser that is easier for agents to operate", but to give agents a native web access interface:

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

WebFA is not a traditional browser UI, not a site-specific API wrapper, and not an autonomous agent.
The agent decides what to do. WebFA opens real websites, keeps the local user's login profile, returns structured page state, and performs generic web-object actions.

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
- Managed Chromium runtime path with persistent local profile and no Playwright dependency.
- Agent-readable `WebState` with WebObjects, relations, capabilities, document revisions, ChangeSets, auth status, and takeover state.
- `webfa.act` accepts declared semantic operations only; click/type/press remain internal Runtime strategies.
- WebFA-owned Auth Surface by default for user-assisted login, QR, verification, 2FA, and authorization pages.
- Single active agent lease so multiple connected agents do not silently fight over one browser session.
- WebFA Visualizer MVP for Runtime status, page preview, Agent View, Safety Center, Step-up, and safety receipts. The complete `/v1/visualizer/*` control plane uses a separate high-entropy token and is isolated from Agent REST/MCP calls.
- P11 safety enforcement for task-scoped SafetyContext, Runtime evidence elevation, Profile/Origin binding, exact single-use Step-up, credential takeover, resource grants, and financial policy.

## Current Limits

- The Visualizer is currently an inspector and takeover panel, not a complete desktop browser. Login and QR flows should happen in the WebFA takeover area.
- All agents connected to the same Runtime and `WEBFA_HOME` share the default browser profile and website login state.
- Multi-profile and multi-session isolation are not implemented yet.
- WebFA does not bypass anti-bot, CAPTCHA, risk-control, or platform safety systems.
- SafetyContext, Step-up, financial usage, resource grants, and SafetyReceipt state are still session-local. Crash restoration and durable state belong to P13.
- `open_url` and link navigation are still modeled as navigation. If a site abuses GET navigation to perform an external write, Runtime cannot determine that business side effect from protocol semantics alone; this remains a documented boundary.
- Some historical transaction/provider code remains in the repository as legacy code. Primitive BrowserAction REST is disabled by default and is not exposed through MCP.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
npm install
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

`webfa-mcp` reuses an already-running Runtime. If none is reachable at `WEBFA_RUNTIME_URL`, it starts one automatically.

Start the complete development Visualizer (Renderer + Electron; Electron generates the control token and starts Runtime):

```powershell
npm run dev
```

`npm run dev:renderer` starts only the static Renderer and does not receive a securely injected Visualizer control token, so it is not a complete control plane.

Default URL:

```text
http://127.0.0.1:8788
```

## Configure an Agent

Generate a standard MCP config:

```powershell
webfa mcp-config --agent-id codex
```

Generate an opencode config:

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

Each agent should use a distinct `WEBFA_AGENT_ID`. WebFA allows one active agent to change browser state at a time. Other agents can still observe and will see the active lease in `WebState` and `/health`.

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

Developer Preview uses the WebFA-owned Auth Surface as the main authentication path. Agents should not type passwords, verification codes, or 2FA codes. When a page enters a login, QR-code, verification-code, 2FA, or authorization flow, the user completes authentication in the central WebFA takeover area, then the agent continues with `webfa.observe`.

`webfa login` remains as a manual pre-login helper. A separate visible host is only a legacy fallback and requires explicitly setting `WEBFA_AUTH_SURFACE_MODE=legacy`.

## Environment

Copy `.env.example` for local notes if needed. Common variables:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"  # the only supported BrowserHost path
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
# A standalone Runtime must receive an explicit high-entropy value before its Visualizer control plane can be used:
$env:WEBFA_VISUALIZER_CONTROL_TOKEN="<random-secret>"
# Historical regression only; never enable in production:
# $env:WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API="1"
```

If `WEBFA_HOME` is unset on Windows, WebFA uses `%APPDATA%\WebFA`.

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

Current milestone: P10 WebFA Object Model and P11 Agent Safety Contract are complete. The complete P12 Multi Session / Multi Profile target architecture is frozen, and P12.1-P12.6 are implemented: persistent Profile Catalog, isolated Profile storage and Chromium Hosts, cross-process Profile locks, BrowserSessionRuntime, concurrent multi-Profile SessionManager/Supervisor routing, connection-scoped Profile grants, Session-exclusive Agent leases, global Tab/WebObject routing, five-tool `profile_ref` integration, Session-specific Monitor grants, VisualStreamHub, and independent HumanControl isolation. P12.7 P11 authority re-scoping and adversarial security review is next. See `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`, `docs/reports/P12_1_3_PROFILE_SESSION_FOUNDATION_REPORT.md`, and `docs/reports/P12_4_6_MULTI_SESSION_ROUTING_MONITOR_REPORT.md`.

Next work:

- P12 Multi Session / Multi Profile
- P13 Durable Trace / Resume

## License

MIT. See `LICENSE`.
