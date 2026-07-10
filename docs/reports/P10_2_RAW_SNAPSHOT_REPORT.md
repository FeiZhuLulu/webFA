# P10.2 RawWebSnapshot Collector Report

Date: 2026-07-11

## Status

P10.2 is complete.

WebFA now has an internal RawWebSnapshot path that collects WebFA-owned browser evidence from Managed Chromium while preserving the current BrowserState/P7 compatibility path.

## Delivered

- `RawWebSnapshot` internal model
- normalized accessibility nodes from `Accessibility.getFullAXTree`
- normalized DOM/layout documents from `DOMSnapshot.captureSnapshot`
- engine frame metadata from `Page.getFrameTree`
- `RawSnapshotCollector`
- `HostBrowserDriver.observe_web_raw()`
- projection from RawWebSnapshot back to legacy `RawPageSnapshot`
- password-value sanitization in the existing observe probe
- allowlisted DOM attributes only; input values and arbitrary data attributes are not retained
- recoverable evidence errors when a host cannot provide optional P10 evidence

## Security Boundary

Raw AX/DOM/CDP evidence is internal only.

The formal Agent-facing WebState schema explicitly forbids:

- accessibility nodes
- DOM documents
- engine frame internals
- backend node IDs
- AX node IDs
- provenance/debug evidence
- raw DOM, HTML, selectors, XPath, CDP, or evaluate escape hatches

Editable AX values are removed, password values are cleared in the legacy probe, and DOM snapshot normalization omits input-value columns and non-allowlisted attributes.

## Compatibility

Current Runtime behavior remains unchanged:

```text
Managed Chromium
  -> RawWebSnapshot
  -> RawPageSnapshot compatibility projection
  -> AgentViewBuilder
  -> BrowserState
```

P10.3 will introduce WebObjectCompiler alongside this compatibility projection.

## Validation

```text
P10.2 focused raw snapshot tests: passed
Managed Chromium integration tests: 7 passed
Full Python suite: 284 passed
Renderer typecheck: passed
Electron typecheck: passed
Python package build: passed
```

The real Chromium validation confirms that accessibility nodes, DOM documents, and engine frame evidence are non-empty on the WebFA validation fixture.

## Next

P10.3 WebObjectCompiler:

- deterministic category and role classification
- object names and state
- parent/child and semantic relations
- capability derivation
- document outline and regions
- debug provenance
- no LLM and no site-specific rules
