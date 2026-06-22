# WebFA + Claude Code

Add WebFA as a local MCP server:

```json
{
  "mcpServers": {
    "webfa": {
      "command": "webfa-mcp",
      "args": [],
      "env": {
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787",
        "WEBFA_AGENT_ID": "claude-code",
        "WEBFA_BROWSER_DRIVER": "managed-chromium",
        "WEBFA_AUTH_TAKEOVER": "auto"
      }
    }
  }
}
```

Validation prompt:

```text
Use only WebFA MCP tools. Do not use bash, curl, Playwright, browser plugins, or
site APIs. Open https://example.com, report title and visible text, then use the
local WebFA validation fixture to enter Fei and submit the form.
```

Notes:

- WebFA does not expose cookies, storage, tokens, selectors, raw CDP, or raw
  Playwright.
- The default profile is shared across agents that connect to the same Runtime.
- `409 agent_busy` means another agent owns the browser lease.
