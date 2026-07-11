# P10.8 Opaque Surface and Human Takeover Report

Status: complete

## Scope

P10.8 makes inability explicit. WebFA no longer needs to pretend that every rendered region is a normal semantic control.

Implemented:

- visible `canvas`, `embed`, and `object` DOM surfaces can compile into `opaque_surface` WebObjects;
- opaque objects carry a deterministic reason such as `canvas_without_semantic_objects`;
- opaque objects expose only `request_human_takeover` and never screenshot-coordinate or selector capabilities;
- DOM bounds are used only internally to decide whether a rendered opaque surface is visible enough to report; bounds are not exposed to agents;
- Runtime takeover state now preserves reason, target, origin, URL, and active status;
- authentication is one takeover reason rather than the takeover model itself;
- `BrowserRuntime.observe_web()` preserves opaque/file/ambiguous takeover reasons instead of rewriting them as authentication;
- Visualizer now receives both legacy `BrowserState` and P10 `WebState`, plus a generalized `takeover_surface` payload;
- the existing Electron takeover viewport is reused for authentication and non-authentication human steps;
- Visualizer messaging distinguishes authentication from opaque-surface handling;
- agent-state copy prefers WebState when available.

## Opaque Surface Rule

P10.8 currently recognizes visible rendered surfaces backed by:

```text
canvas
embed
object
```

A surface is not emitted as opaque when the same backend DOM node has already been compiled into a stronger semantic WebObject. This avoids replacing valid accessible controls with an opaque fallback.

## Human Takeover Contract

The active takeover preserves:

```text
reason
target
origin
url
resume_operation = observe
```

Supported reasons remain the complete P10 schema set, including authentication, captcha, opaque_surface, file_selection, permission_request, ambiguous_state, and manual confirmation categories.

## Verification

- focused Runtime, Visualizer, and Managed Chromium tests: 18 passed;
- full Python test suite: 336 passed, 2 deprecation warnings;
- renderer TypeScript typecheck: passed;
- Electron TypeScript typecheck: passed;
- Python sdist and wheel build: passed;
- real Chromium Canvas fixture compiles to an opaque_surface with human takeover capability.

## Boundary

P10.8 does not add visual coordinate control. It also does not expose the P10 protocol through public MCP/REST yet. Public migration and removal of the old compatibility surface remain P10.9.
