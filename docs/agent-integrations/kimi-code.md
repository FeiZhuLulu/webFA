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
        "WEBFA_AGENT_ID": "kimi-code"
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
- Use a distinct stable `WEBFA_AGENT_ID` for each external Agent client.
- Omitting `profile_ref` uses the configured default Profile. Pass an authorized
  Profile alias to `webfa.open_url` to select another internet identity.
- One persistent Profile has at most one writable Session; different Profile
  Sessions can run concurrently. `session_busy` or legacy `agent_busy` means
  another connection owns the relevant lease.
- Browser mode and HumanControl policy belong to the Runtime host, not to the
  Kimi Code MCP configuration.
