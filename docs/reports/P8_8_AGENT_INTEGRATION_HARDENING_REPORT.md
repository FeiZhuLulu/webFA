# P8.8 Agent Integration Hardening Report

## Goal

P8.8 makes WebFA safer for multiple external MCP agents connected to the same
local Runtime. It does not add browser actions or site-specific behavior.

## Changes

- Added active agent lease for browser-changing operations.
- MCP now sends `X-WebFA-Agent-Id` from `WEBFA_AGENT_ID`.
- Runtime returns `409 agent_busy` when another agent owns the active lease.
- `observe`, `tabs`, and `/health` remain read-only and show active agent state.
- BrowserState now includes safe agent/profile metadata.
- MCP config generation includes `WEBFA_AGENT_ID` and can emit opencode config.
- Agent integration docs now cover opencode, Kimi Code, Claude Code, and Codex.

## Boundaries

- One Runtime, one default session, one default shared profile.
- No multi-profile UI, no new MCP tools, no release endpoint.
- No cookies, storage, tokens, passwords, or profile internals are exposed.

## Automated Verification

```text
python -m pytest tests/unit/test_agent_lease.py tests/unit/test_mcp_config_generator.py tests/unit/test_runtime_client_headers.py tests/unit/test_cli_entrypoints.py tests/unit/test_mcp_error_mapping.py tests/integration/test_agent_lease_api.py -q
  -> 34 passed

python -m pytest -q
  -> 201 passed, 2 warnings

npm run typecheck:renderer
  -> passed

npm run typecheck:electron
  -> passed

python -m build
  -> built sdist and wheel
```
