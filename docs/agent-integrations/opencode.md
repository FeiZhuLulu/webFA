# WebFA + opencode

Use opencode's local MCP config shape, not `mcpServers`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "webfa": {
      "type": "local",
      "enabled": true,
      "command": ["webfa-mcp"],
      "environment": {
        "WEBFA_RUNTIME_URL": "http://127.0.0.1:8787",
        "WEBFA_AGENT_ID": "opencode",
        "WEBFA_BROWSER_DRIVER": "managed-chromium",
        "WEBFA_AUTH_TAKEOVER": "auto"
      }
    }
  }
}
```

If using the repo virtual environment directly, replace `webfa-mcp` with:

```json
["E:/项目库/webFA/webfa-phase1/.venv/Scripts/webfa-mcp.exe"]
```

Validation prompt:

```text
Use only WebFA MCP tools. List available tools, then open https://example.com,
report the title and main visible text, then open
E:/项目库/webFA/webfa-phase1/tests/fixtures/agent_validation_page.html,
enter Fei, click Submit, and confirm Hello Fei.
```

Notes:

- Default tools should be exactly `webfa.open_url`, `webfa.observe`,
  `webfa.act`, `webfa.get_tabs`, `webfa.switch_tab`.
- WebFA uses the shared default profile. opencode sees the same logged-in
  website accounts as other agents connected to the same Runtime.
- If Runtime returns `409 agent_busy`, another agent currently owns the browser
  lease. Wait for the lease to expire or stop using the other agent.
