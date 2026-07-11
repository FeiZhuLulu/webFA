# P10.7 Structured Reading Report

Status: complete

## Scope

P10.7 makes document structure first-class in the Web Object model instead of leaving agents to infer structure from flat text.

Implemented:

- explicit `fields`, `items`, `rows`, `cells`, and `headers` relations;
- relation rewriting in `ObjectRegistry` so stable object IDs are preserved across all structured-reading links;
- range reads based on semantic collection membership rather than only generic children;
- deterministic AX-subtree text aggregation for Chrome nodes such as `listitem` and `status` whose own accessible name is empty;
- compiler normalization for form fields, list/collection items, table rows, cells, and headers;
- observable item counts and visible ranges derived from semantic relations;
- synthetic gold tests for document, form, collection, table, dialog/status, and frame structure;
- real Managed Chromium regression using `tests/fixtures/structured_reading_page.html`.

## Important Finding

Chrome commonly exposes `listitem` and live-status objects with an empty node name while their readable text is stored in descendant `StaticText` nodes. The compiler now aggregates bounded descendant AX text deterministically. This is a browser-evidence normalization rule, not an LLM heuristic.

## Agent-facing Result

Agents can now inspect and query explicit relations such as:

```text
form -> fields
list/collection -> items
table -> rows -> cells
table -> headers
```

Collection range reads use these semantic relations and return the selected children as WebObjects.

## Verification

- focused structured-reading and Managed Chromium tests: 13 passed;
- full Python test suite: 333 passed, 2 deprecation warnings;
- renderer TypeScript typecheck: passed;
- Electron TypeScript typecheck: passed;
- Python sdist and wheel build: passed.

## Boundary

This phase does not expose the P10 path through public MCP/REST yet. `BrowserRuntime.observe_web()` and `BrowserRuntime.act_web()` remain internal migration paths. Opaque surfaces and generalized takeover are P10.8.
