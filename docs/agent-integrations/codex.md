# WebFA + Codex

Use WebFA through the local MCP server:

```json
{
  "mcpServers": {
    "webfa": {
      "command": "webfa-mcp",
      "args": [],
      "env": {
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787",
        "WEBFA_AGENT_ID": "codex",
        "WEBFA_BROWSER_DRIVER": "managed-chromium",
        "WEBFA_AUTH_TAKEOVER": "auto"
      }
    }
  }
}
```

Validation prompt:

```text
Use only WebFA MCP tools. Confirm tool list, open https://example.com, read the
title and visible text, then complete the local WebFA validation page by typing
Fei and clicking Submit.
```

Notes:

- All connected agents share the same default website login state unless they
  use a different `WEBFA_HOME`.
- Only one agent should control the browser at a time. WebFA enforces this with
  an active agent lease.
