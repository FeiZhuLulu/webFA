# P10.9A Public Agent Surface Migration Report

Status: complete

## Scope

P10.9A moves the default five MCP tools from the legacy BrowserState/BrowserAction protocol onto the P10 WebState/WebObject protocol without changing tool names.

## Public MCP Contract

The default tools remain exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Their semantics are now:

- `open_url` returns WebState;
- `observe` supports page, object, query, and changes modes;
- `act` accepts only a semantic operation, target WebObject id, operation arguments, and optional expected object version;
- tool schemas enumerate supported observe modes, detail levels, and semantic operations;
- `action`, click, type, press, focus, selector, XPath, raw DOM, Playwright, and CDP are absent from the default Agent surface.

## Runtime REST Surface

Added P10 routes:

```text
POST /v1/browser/web/open
POST /v1/browser/web/observe
POST /v1/browser/web/act
POST /v1/browser/web/tabs/switch
```

Legacy BrowserState/BrowserAction REST routes remain temporarily as compatibility-only endpoints for internal regression tests. Default MCP does not call them.

## Dialog Reliability Fix

JavaScript dialogs block normal page evaluation and CDP evidence collection. HostBrowserDriver now retains the last safe RawWebSnapshot and, while a dialog is active, reuses it with fresh dialog evidence. This lets an Agent observe the dialog WebObject and call the semantic `dismiss` operation without bypassing browser state.

## Verification

- public MCP stdio open/observe/act/observe loop uses WebObjects and semantic operations;
- public MCP dialog flow uses activate -> observe dialog object -> dismiss;
- public REST WebObject loop uses set_value and submit;
- public REST rejects browser primitive operations and selector queries;
- MCP input schema includes operation and observe modes but no action field;
- full Python test suite: 338 passed, 2 deprecation warnings;
- renderer TypeScript typecheck: passed;
- Electron TypeScript typecheck: passed;
- Python sdist and wheel build: passed.

## Remaining P10.9 Work

- remove Playwright dependency and factory/config paths;
- stop packaging the Playwright driver implementation;
- retire or isolate legacy BrowserState/BrowserAction REST endpoints after their tests are migrated;
- update current public documentation and final P10 acceptance report.
