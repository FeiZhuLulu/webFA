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
        "WEBFA_AGENT_ID": "claude-code"
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
- Use a distinct stable `WEBFA_AGENT_ID` for each external Agent client.
- Omitting `profile_ref` uses the configured default Profile. Pass an authorized
  Profile alias to `webfa.open_url` to select a different internet identity.
- A persistent Profile has at most one active writable Session; different
  Profiles can run concurrently. `session_busy` or legacy `agent_busy` means
  another connection holds the relevant lease.
- Browser mode and HumanControl policy are Runtime-host settings and do not
  belong in Claude Code's MCP configuration.
