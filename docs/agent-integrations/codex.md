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
        "WEBFA_AGENT_ID": "codex"
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

- `WEBFA_AGENT_ID` identifies this external client; use a distinct stable value
  for every Agent configuration.
- Omitting `profile_ref` uses the configured default Profile. Pass an authorized
  Profile alias such as `work` to `webfa.open_url` to select another internet
  identity; tab results include their `profile_ref`.
- A persistent Profile has at most one active writable Session. Sessions on
  different Profiles can run concurrently. `session_busy` or legacy
  `agent_busy` means another connection currently holds the relevant lease.
- Browser mode and HumanControl policy belong to the Runtime host, not to the
  Codex MCP client configuration.
