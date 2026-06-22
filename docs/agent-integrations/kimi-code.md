# WebFA + Kimi Code

Configure Kimi Code with an MCP server entry that launches `webfa-mcp`.

```json
{
  "mcpServers": {
    "webfa": {
      "command": "webfa-mcp",
      "args": [],
      "env": {
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787",
        "WEBFA_AGENT_ID": "kimi-code",
        "WEBFA_BROWSER_DRIVER": "managed-chromium",
        "WEBFA_AUTH_TAKEOVER": "auto"
      }
    }
  }
}
```

Validation prompt:

```text
Use only WebFA MCP tools. Confirm the five WebFA tools are available. Open
https://example.com and report URL, title, visible text, and interactive
elements. Then run the local WebFA validation fixture and confirm Hello Fei.
```

Notes:

- Kimi Code may require a client restart before MCP tools appear.
- WebFA uses one shared default profile, so logged-in websites are the local
  user's accounts.
- If `409 agent_busy` appears, another agent has the active browser lease.
