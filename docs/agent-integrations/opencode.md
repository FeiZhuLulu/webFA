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
        "WEBFA_AGENT_ID": "opencode"
      }
    }
  }
}
```

If using the repo virtual environment directly, replace `webfa-mcp` with the
absolute path to your local executable, for example:

```json
["<absolute-path-to-webfa-mcp>"]
```

Validation prompt:

```text
Use only WebFA MCP tools. List available tools, then open https://example.com,
report the title and main visible text, then open
<your-webfa-repo>/tests/fixtures/agent_validation_page.html,
enter Fei, click Submit, and confirm Hello Fei.
```

Notes:

- Default tools should be exactly `webfa.open_url`, `webfa.observe`,
  `webfa.act`, `webfa.get_tabs`, `webfa.switch_tab`.
- Use a distinct stable `WEBFA_AGENT_ID` for each external Agent client.
- Omitting `profile_ref` uses the configured default Profile. Pass an authorized
  Profile alias to `webfa.open_url` to select another internet identity.
- One persistent Profile has at most one writable Session; different Profile
  Sessions can run concurrently. `session_busy` or legacy `agent_busy` means
  another connection owns the relevant lease.
- Browser mode and HumanControl policy belong to the Runtime host, not to the
  opencode MCP configuration.
