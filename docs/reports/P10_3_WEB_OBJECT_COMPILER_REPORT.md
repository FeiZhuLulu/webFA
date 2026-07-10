# P10.3 WebObjectCompiler Report

Date: 2026-07-11

## Status

P10.3 is complete.

WebFA now has a deterministic WebObjectCompiler that converts RawWebSnapshot evidence into the P10 WebState/WebObject model while the public Runtime continues using the BrowserState/P7 compatibility path.

## Delivered

- `WebObjectCompiler`
- internal `WebObjectCompilation` and debug-only provenance records
- deterministic Category and Role classification
- document root and frame objects
- AX-derived structural objects and heading outline
- content objects and major region references
- interactive objects derived from merged probe, AX, and DOM evidence
- form objects with field and submit-control relations
- semantic capability derivation with no agent-visible click/type/press/focus
- cross-origin frame metadata
- transient JavaScript dialog objects
- authentication takeover mapped to the relevant password WebObject
- generic degraded-evidence errors without leaking raw collector details

## Deterministic Boundary

The compiler uses only browser evidence and fixed rules:

- accessibility roles, names, properties, and node continuity evidence
- sanitized DOM attributes and backend-node evidence
- existing safe content/form/interactive probe output
- frame, dialog, auth, and runtime state

It does not use an LLM, suggested actions, site-specific parsers, raw selectors, or business-action inference.

## Capability Boundary

Formal object capabilities include semantic operations such as:

- `open`
- `activate`
- `set_value`
- `clear_value`
- `choose`
- `toggle`
- `submit`
- `expand` / `collapse`
- `dismiss`
- `upload`
- `request_human_takeover`

Legacy click/type/press/focus evidence may inform internal compilation, but those primitives never appear in WebObject capabilities.

Password fields expose only `request_human_takeover` and never expose their value.

## Compatibility

Current public behavior remains unchanged:

```text
RawWebSnapshot
  -> RawPageSnapshot compatibility projection
  -> AgentViewBuilder
  -> BrowserState
```

P10.3 adds a parallel target path:

```text
RawWebSnapshot
  -> WebObjectCompiler
  -> WebState + internal provenance
```

P10.4 will add ObjectRegistry identity reconciliation, object versions, document revisions, and ChangeSets before WebState is wired into public observe.

## Validation

```text
WebObjectCompiler gold tests: 8 passed
Real Managed Chromium WebObject compilation: passed
Full Python suite: 293 passed
Renderer typecheck: passed
Electron typecheck: passed
Python package build: passed
```

Validated behavior includes:

- outline and region generation
- form and content ownership relations
- semantic capabilities
- duplicate same-name heading preservation
- cross-origin frame security metadata
- transient dialog objects
- password takeover behavior
- provenance isolation from WebState
- graceful partial-evidence compilation

## Next

P10.4 Identity and ChangeSet:

- stable identity reconciliation from backend-node, AX, semantic, and structural evidence
- object version increments for meaningful object changes
- document revision increments for meaningful page changes
- compact added/updated/removed/invalidated ChangeSets
- SPA-noise filtering
