# WebFA External Agent Entry Package

The installed WebFA entry package exposes the current P4-P12 agent-native local
Runtime to independent external Agents without requiring repository-only
commands. Historical P1-P3 transaction components remain packaged for explicit
legacy compatibility but are disabled from the default Agent surface. WebFA does
not create, plan for, or run an Agent; each client decides its own work and owns
its MCP stdio connection.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

For a built wheel, install the wheel into a fresh virtual environment and use
the same commands below.

## Commands

```powershell
webfa-runtime
```

Starts the local FastAPI Runtime on `127.0.0.1:8787`.

```powershell
webfa-mcp
```

Runs the MCP stdio server. It reuses only a Runtime with a compatible WebFA
identity. Auto-start is allowed only for an unreachable loopback HTTP endpoint;
an endpoint lock coalesces concurrent starts and each MCP client holds a stable-
process-identity lease. The last live owner stops only an MCP-auto-started
Runtime, never an external or Desktop-owned Runtime.

```powershell
webfa mcp-config
```

Prints MCP client configuration using the installed command:

```json
{
  "mcpServers": {
    "webfa": {
      "command": "webfa-mcp",
      "args": [],
      "env": {
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787",
        "WEBFA_AGENT_ID": "external-agent"
      }
    }
  }
}
```

Replace `external-agent` with a stable, distinct identity for each Agent client.

```powershell
webfa doctor
```

Runs a local smoke test:

- Runtime health
- managed-chromium default driver
- Chromium executable availability
- default 5 MCP browser tools
- local fixture open/fill/submit loop
- no cookie/storage/token/full DOM leak in returned state

```powershell
webfa login github
webfa login --url https://example.com/login
```

Opens a visible login window using the default WebFA managed-chromium profile.
The user signs in manually, including password, QR code, 2FA, or authorization
prompts. WebFA does not ask an agent to type credentials and does not store
passwords. When the user presses Enter in the CLI, WebFA closes the window and
keeps the browser profile for future agent sessions.

## Environment

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_HOME="$env:APPDATA\WebFA"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"  # legacy visible-host compatibility only
```

`WEBFA_HOME` is optional for source runs and standalone Python/CLI entry points.
If unset on Windows, those entry points use:

```text
%APPDATA%\WebFA
```

Packaged Desktop does not inherit an arbitrary parent `WEBFA_HOME`. It forces
the bundled Runtime's `WEBFA_HOME` to Electron `app.getPath("userData")`, so
Profile, Session, lock, and Runtime state stay beneath the Desktop-owned
application-data root rather than an inherited path or the program directory.

The default persistent BrowserProfile is stored at:

```text
%APPDATA%\WebFA\profiles\default\chromium-user-data
```

P12 supports multiple isolated BrowserProfiles. Each active persistent Profile
uses its own Chromium user-data directory, Managed Chromium Host, and writable
BrowserSession. Agents use the optional `profile_ref` argument on
`webfa.open_url` to enter an authorized Profile; no Profile-management tools are
exposed through MCP.

Set a distinct `WEBFA_AGENT_ID` in each agent's MCP config. A writable Session is
exclusive to one Agent connection, while different authorized Profiles can run
concurrently. Attempts to write through another connection return a structured
Session/Profile busy error. `webfa.get_tabs` lists only Sessions authorized for
the current connection.

The default lease is 10 minutes. Every successful five-tool call renews a
still-active connection and Session lease; an expired lease is never
resurrected by read activity:

```powershell
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
```

Use `webfa login github` to put a GitHub login session into this profile before
asking an agent to work on logged-in GitHub pages.

Developer preview uses Session Monitor's projection of the same BrowserHost
page for authentication takeover. If an agent opens a login, QR-code,
verification-code, 2FA, or authorization page, the user opens that Session's
Monitor and acquires a time-bounded `HumanControlLease`. Local mouse, keyboard,
wheel, paste, and composition input is forwarded to the existing page target;
no duplicate page, second BrowserHost, or DOM bridge is created. The agent does
not receive passwords, verification codes, cookies, storage values, or tokens.
When page keyboard capture has focus, Escape returns to the visible Page
Keyboard control without releasing the lease. Enter resumes page capture, while
Tab reaches Return to Agent. Lease release remains available while connected
even if the latest visual frame is temporarily unavailable.

HumanControl authority is bound to the authenticated Monitor connection,
Profile, Session, active tab, and Runtime generation. Agent writes pause only in
that Session while the lease is active. Release, expiry, revocation, disconnect,
or Monitor closure restores Runtime control, after which the agent performs a
fresh `webfa.observe`. The former duplicate-page Electron AuthSurface is
permanently retired and does not close or restart BrowserHost.

The legacy visible-host compatibility path can disable automatic relaunch for
tests or fully unattended local smoke runs. This variable does not enable,
disable, or authorize Session Monitor HumanControl:

```powershell
$env:WEBFA_AUTH_TAKEOVER="off"
```

## Agent Contract

Default MCP tools remain exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Legacy transaction tools appear only when:

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

WebFA does not expose raw Playwright, CDP, selectors, XPath, DevTools, site APIs,
cookies, storage, or tokens as agent-facing capabilities.

## Manual Validation

Automated tests cover installed-wheel behavior, frozen sidecar MCP, release
inputs, unpacked integrity, and packaged lifecycle smoke. A real external Agent
workflow against the exact release candidate remains an explicit candidate gate:

1. Install WebFA in a clean environment.
2. Add `webfa mcp-config` output to the agent's MCP configuration.
   Use `--agent-id opencode`, `--agent-id kimi-code`, etc. for each client.
3. Start the agent.
4. Confirm the agent sees only the five default tools.
5. Run a local `open_url -> observe -> act -> observe` task.
