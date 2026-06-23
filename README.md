# WebFA

WebFA is a local **agent-native browser runtime**.

It lets external agents use the web through a small MCP interface:

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

WebFA is not a traditional browser UI, not a site-specific API wrapper, and not
an autonomous agent. The agent decides what to do. WebFA opens real websites,
keeps the local user's login profile, returns structured page state, and
performs generic web-object actions.

Status: **developer preview**. APIs and behavior may change.

## What Works Today

- MCP stdio entry point for external agents.
- Five default MCP tools:
  - `webfa.open_url`
  - `webfa.observe`
  - `webfa.act`
  - `webfa.get_tabs`
  - `webfa.switch_tab`
- Managed Chromium runtime path with persistent local profile.
- Agent-readable `BrowserState` with URL parts, forms, elements, content blocks,
  auth status, and active agent lease metadata.
- Generic actions for forms, links, controls, lists, blocks, and fallback
  primitives such as click/type/press.
- User-assisted login takeover for password, QR, verification, 2FA, and
  authorization pages.
- Single active agent lease so multiple connected agents do not silently fight
  over one browser session.

## Current Limits

- Visible auth takeover still uses a managed Chromium window.
- All agents connected to the same Runtime and `WEBFA_HOME` share the default
  browser profile and website login state.
- Multi-profile and multi-session isolation are not implemented yet.
- WebFA does not bypass anti-bot or platform risk systems.
- High-risk final actions such as send, delete, purchase, publish, or settings
  changes do not yet have a complete confirmation layer.
- Some historical transaction/provider code remains in the repository as
  legacy code and is disabled from the default MCP surface.

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

`webfa-mcp` reuses an already-running Runtime. If none is reachable at
`WEBFA_RUNTIME_URL`, it starts one automatically.

## Configure an Agent

Generate a standard MCP config:

```powershell
webfa mcp-config --agent-id codex
```

Generate an opencode config:

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

Each agent should use a distinct `WEBFA_AGENT_ID`. WebFA allows one active
agent to change browser state at a time. Other agents can still observe and
will see the active lease in `BrowserState` and `/health`.

Integration docs:

- `docs/agent-integrations/opencode.md`
- `docs/agent-integrations/kimi-code.md`
- `docs/agent-integrations/claude-code.md`
- `docs/agent-integrations/codex.md`

## Login

Open a manual login window for the default WebFA profile:

```powershell
webfa login github
webfa login --url https://example.com/login
```

Agents should not type passwords or verification codes. When WebFA detects a
login, QR-code, verification-code, 2FA, or authorization page in headless mode,
it can automatically reopen the same page in a visible managed Chromium window.
The user completes authentication manually, then the agent continues with
`webfa.observe`.

## Environment

Copy `.env.example` for local notes if needed. Common variables:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"
$env:WEBFA_BROWSER_HEADLESS="1"
$env:WEBFA_AUTH_TAKEOVER="auto"
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
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

WebFA should not expose these to agents:

- cookies
- localStorage/sessionStorage values
- tokens or authorization headers
- password values
- raw Playwright
- raw CDP
- selector/XPath/evaluate escape hatches
- full DOM/HTML by default

Default MCP tools must remain exactly the five browser tools. Legacy
transaction MCP tools appear only when explicitly enabled:

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

## Roadmap

See `docs/browser-runtime-roadmap.md`.

Near-term work:

- P9 WebFA Visualizer
- P10 Element Registry v2
- P11 Multi Session / Multi Profile
- P12 Real Task Safety Layer

## License

MIT. See `LICENSE`.
