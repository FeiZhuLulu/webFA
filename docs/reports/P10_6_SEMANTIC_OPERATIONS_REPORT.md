# P10.6 Semantic Operations Report

Status: complete for the current BrowserHost capability surface

## Delivered

- Added the complete WebFA Object capability descriptor registry, including effect metadata for the future P11 safety layer.
- Added `SemanticOperationExecutor` with object existence, capability, visibility, enabled-state, argument, and object-version validation.
- Added explicit structured operation failures: object not found, version conflict, unsupported capability, invalid arguments, and temporarily unavailable execution.
- Added internal semantic mappings for:
  - `open`
  - `activate`
  - `set_value`
  - `clear_value`
  - `choose`
  - `toggle`
  - `submit`
  - `expand`
  - `collapse`
  - `dismiss`
  - `request_human_takeover`
- Added `BrowserRuntime.act_web()` as the internal P10 operation path while preserving the public BrowserState/P7 compatibility path.
- Semantic operations return stable object versions, document revisions, updated WebState, and explicit no-op results.
- Low-level `click`, `type`, `press`, `clear`, and `select` remain internal execution strategies and are not added to the WebObject protocol.
- File inputs compile as `upload_target` with human takeover until the approved resource bridge exists; they do not falsely advertise `upload`.
- AX-only objects remain readable until the BrowserHost can execute against backend/AX node identities directly; they do not falsely advertise unsupported expand/collapse operations.

## Deliberately Incomplete Implementation Coverage

The complete target model still includes:

- `open_in_new_context`
- `download`
- `upload`

These capabilities are defined in the capability registry but are not currently advertised by compiled objects or dispatched by the executor. They require tab/resource-domain implementations rather than temporary path- or event-based shortcuts.

This is incomplete engineering coverage, not a reduced product model.

## Boundaries

- Default MCP tool count remains five.
- Public MCP/REST `act` has not yet migrated to `WebOperationRequest`.
- No selector, XPath, raw DOM, raw CDP, or evaluate interface was added.
- Capability declarations must remain truthful: objects only advertise operations executable through the current BrowserHost or explicit takeover.
- P11 will enforce authority and confirmation for capability effects such as `external_write`, `upload`, and destructive operations.

## Validation

```text
Focused P10.6 tests: 39 passed
Full pytest: 330 passed, 2 warnings
Renderer typecheck: passed
Electron typecheck: passed
Python package build: passed
```

## Next

P10.7 Structured Reading: improve document, collection, table, form, dialog/status, and frame objects so the new observe protocol can represent complex pages without reducing them to flat text blocks.
