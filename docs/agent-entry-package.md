# WebFA Agent Entry Package

P8 makes WebFA usable as a local agent runtime without requiring users or agents
to remember repository-only commands.

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

Runs the MCP stdio server. It checks `WEBFA_RUNTIME_URL`; if no Runtime is
reachable, it starts a local Runtime subprocess and waits for `/health`.

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
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787"
      }
    }
  }
}
```

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
$env:WEBFA_BROWSER_HEADLESS="1"
$env:WEBFA_AUTH_TAKEOVER="auto"
```

`WEBFA_HOME` is optional. If unset on Windows, WebFA uses:

```text
%APPDATA%\WebFA
```

The default browser profile is:

```text
%APPDATA%\WebFA\browser\managed-chromium-profile-default
```

This default profile is shared. If Kimi Code, Claude Code, Codex, and opencode
all connect to the same Runtime and `WEBFA_HOME`, they use the same website
login state. This is intentional for the early local runtime: WebFA represents
the local user's browser identity, not a separate account per agent.

Set a distinct `WEBFA_AGENT_ID` in each agent's MCP config. WebFA allows one
active agent to control the browser at a time. If another agent tries to open,
act, or switch tabs while the lease is active, Runtime returns `409 agent_busy`.
Read-only observe/tabs/health calls remain available and show the active agent.

The default lease is 10 minutes and renews on each browser-changing action:

```powershell
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
```

Use `webfa login github` to put a GitHub login session into this profile before
asking an agent to work on logged-in GitHub pages.

By default, WebFA also performs automatic auth takeover. If an agent opens a
login, QR-code, verification-code, 2FA, or authorization page while the Runtime
is headless, WebFA relaunches the same page in a visible managed Chromium
window using the same default profile. The user completes the credential step
manually, then the agent continues with `webfa.observe`.

Disable this behavior only for tests or fully unattended local smoke runs:

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

The implementation tests cover local packaging and smoke behavior. External
agent validation is intentionally manual for P8:

1. Install WebFA in a clean environment.
2. Add `webfa mcp-config` output to the agent's MCP configuration.
   Use `--agent-id opencode`, `--agent-id kimi-code`, etc. for each client.
3. Start the agent.
4. Confirm the agent sees only the five default tools.
5. Run a local `open_url -> observe -> act -> observe` task.
