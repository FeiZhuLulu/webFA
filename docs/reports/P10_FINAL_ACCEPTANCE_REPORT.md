# P10 WebFA Object Model Final Acceptance Report

Status: accepted

## Product Result

P10 changes the default WebFA Agent surface from DOM-like elements and a global browser-action enum into an agent-native web-object protocol:

```text
Agent
  -> WebState
  -> stable WebObjects
  -> declared capabilities
  -> semantic operations
  -> WebFA Runtime
  -> Managed Chromium BrowserHost
```

The default Agent no longer needs or receives click, type, press, selectors, coordinates, raw DOM, Playwright, or CDP concepts.

## Completed Phases

- P10.0 Definition Freeze
- P10.1 Schema Foundation
- P10.2 RawWebSnapshot Collector
- P10.3 WebObjectCompiler
- P10.4 Stable Identity, Versions, Revisions, and ChangeSets
- P10.5 Queryable Observe
- P10.6 Capability-driven Semantic Operations
- P10.7 Structured Reading
- P10.8 Opaque Surfaces and Generalized Human Takeover
- P10.9 Public Agent Migration, Playwright Removal, Legacy REST Isolation, and Final Documentation

## Default MCP Contract

Exactly five tools remain:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

`webfa.observe` supports:

```text
page
object
query
changes
```

`webfa.act` accepts only semantic operations declared by the target WebObject.

## Object Runtime

P10 delivers:

- WebState and WebObject schemas;
- category and role semantics;
- object state, relations, origin, frame, trust, lifetime, and capabilities;
- capability effect metadata for the P11 safety layer;
- deterministic AX/DOM/layout/runtime evidence compilation;
- stable object IDs across meaningful rerenders;
- object versions and document revisions;
- compact ChangeSets;
- structured document outline and regions;
- form fields and submit relations;
- list/collection items and range reads;
- table rows, cells, and headers;
- dialogs, alerts, status objects, and frames;
- opaque Canvas/embed/object surfaces;
- Human Takeover reasons, targets, origins, and resume behavior;
- Visualizer WebState and takeover integration.

## BrowserHost Boundary

Managed Chromium is the only accepted BrowserHost path.

Removed:

- Python Playwright dependency;
- Playwright config/factory branch;
- Playwright Chromium installation discovery;
- Playwright-backed integration tests;
- Playwright instructions in current validation docs.

A dependency-free compatibility tombstone remains at the historical module path so stale direct imports fail with a clear migration message. It contains no Playwright imports or runtime implementation.

## Legacy Compatibility

BrowserState/BrowserAction compatibility is isolated under:

```text
/v1/browser/legacy/*
```

Old unprefixed URL aliases remain hidden from OpenAPI for one compatibility cycle so historical internal regression tests are not broken abruptly. Default MCP and current Agent documentation do not use them.

## Security and Purity Checks

The P10 Agent surface forbids:

```text
cookies
localStorage / sessionStorage values
tokens and authorization headers
password values
raw HTML / full DOM
selector / XPath / locator
evaluate / raw CDP
Playwright
screenshot-coordinate control
```

Opaque regions are reported explicitly and request Human Takeover rather than silently falling back to visual clicking.

## Verification

Final acceptance run:

- Python tests: 339 passed;
- warnings: 2 upstream websocket deprecation warnings;
- Renderer TypeScript typecheck: passed;
- Electron TypeScript typecheck: passed;
- Python sdist build: passed;
- Python wheel build: passed;
- public MCP stdio WebObject loop: passed;
- public REST WebObject loop: passed;
- JavaScript dialog observe/dismiss loop: passed;
- real Chromium structured-reading regression: passed;
- real Chromium Canvas opaque-surface regression: passed;
- OpenAPI namespace isolation contract: passed;
- package metadata contains no Playwright dependency.

## Next Phase

P11 Real Task Safety Layer should build directly on P10 capability effects, object origin, content trust, semantic operations, versions, ChangeSets, and Human Takeover. It should not reintroduce browser primitives or site-specific transaction APIs.
