# WebFA P8 Validation Report

**Phase**: P8 Plugin-first Packaging / Agent Entry Package  
**Scope**: local Python entrypoints, MCP config, Runtime auto-start, doctor smoke test  
**External agent validation**: deferred to user-run manual testing

## Implemented

- Added console scripts:
  - `webfa`
  - `webfa-runtime`
  - `webfa-mcp`
- `webfa-runtime` starts the local FastAPI Runtime.
- `webfa-mcp` reuses an existing Runtime or auto-starts one when unreachable.
- `webfa mcp-config` emits installed-command MCP config.
- `webfa doctor` runs a local Runtime and browser smoke test.
- Added docs for install, config, environment, and manual agent validation.

## Invariants

- Default MCP tools remain exactly five browser tools.
- managed-chromium remains the default browser runtime path.
- Legacy transaction tools remain opt-in.
- Health and BrowserState must not expose cookies, storage, tokens, full DOM,
  full HTML, or internal debug endpoints.

## Verification

Codex-run checks:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Result:

```text
python -m pytest -q             -> 169 passed, 2 warnings
npm run typecheck:renderer      -> passed
npm run typecheck:electron      -> passed
python -m build                 -> built wheel and sdist
webfa doctor smoke path         -> pass
```

Manual user-run checks:

```powershell
webfa mcp-config
webfa doctor
external agent MCP connection with webfa-mcp
```
