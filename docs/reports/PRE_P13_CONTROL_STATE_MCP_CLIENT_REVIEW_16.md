# Pre-P13 Control State and MCP Client Review — Iteration 16

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration completed the singleton/identity audit across Runtime control
state and the external Agent's MCP process. It preserves the product boundary:
WebFA remains the internet Runtime, each external MCP process remains an Agent-
owned connection, and Desktop remains a lightweight human control surface.

## Defects reproduced

Controlled concurrency and restart tests proved four defects:

1. Twelve simultaneous first control requests created six `ActionLog` objects
   and six `MonitorAccessManager` objects. Requests could therefore write to an
   overwritten log or issue a Monitor token from a manager that later requests
   could not consume.
2. Runtime shutdown/re-entry preserved the previous Monitor manager. A bearer
   token issued by the stopped Runtime generation remained consumable after the
   same ASGI App started again, contradicting the documented non-durable grant
   lifecycle.
3. Twelve concurrent first MCP tool calls constructed twelve
   `WebFARuntimeClient` objects with different connection IDs. The first call
   could acquire P12 authority under one connection and all later calls use the
   overwritten connection identity.
4. Normal or exceptional MCP stdio exit did not close the shared HTTP client.

The pre-fix red tests observed the exact instance counts above and proved both
the stale-token and missing-close behavior.

## Corrections

- `ActionLog` and `MonitorAccessManager` now use locked, double-checked lazy
  publication through the shared App service lock, with safe per-module fallback
  locks for manually assembled apps.
- Runtime shutdown invalidates all Monitor bearer capability state and discards
  action history, preview cache, and obsolete AuthSurface projection state.
- A same-App lifespan re-entry test proves a token from the prior Runtime cannot
  authenticate against the replacement manager.
- MCP now publishes exactly one HTTP client under a process lock, preserving one
  stable MCP connection ID across concurrent tool calls.
- MCP stdio `main()` closes and revokes that client in `finally`, both on normal
  completion and server failure.
- The unused `apps/runtime/api/auth_surface_session.py` module was removed. It
  belonged to the retired duplicate-page AuthSurface and had no importers or
  public route; HumanControl continues through the existing BrowserHost Monitor.

## Verification

- Focused control-state, Monitor, Visualizer, MCP-client, and MCP-tool regression:
  56 passed across the accepted focused runs.
- Final Python suite: 638 passed, 1 skipped, with two third-party websocket
  deprecation warnings.
- Electron and Renderer type checks passed; Electron process/release suite:
  26 passed.
- `git diff --check` passed apart from Windows line-ending notices.
- No Renderer DOM, CSS, or interaction source changed. Desktop remains a thin
  Runtime Manager; this iteration only removes stale/duplicated backing state.

Artifacts under `.release/source-dist/iteration-16`:

- `webfa_desktop_runtime-0.2.0-py3-none-any.whl` — 278,201 bytes — SHA-256
  `A41E536C30B064E30C4924C87B7123400909654303ADE4DEB8B51DA85B9E7024`
- `webfa_desktop_runtime-0.2.0.tar.gz` — 239,008 bytes — SHA-256
  `E0A1FCEC178AA2FAA883A87156165239473BFAFF671BB74633953D39342D6F90`

The wheel contains 159 entries and the sdist 194; neither includes tests or
console source, and the retired AuthSurface module is absent. The wheel was
installed into a source-invisible venv outside the repository. Its import
resolved from that venv, dependency and version checks passed, and `webfa
doctor` passed Runtime health, Managed Chromium, the default MCP tool surface,
and the local Web Object action loop against an explicitly isolated data root.

Generated tracked `webfa_desktop_runtime.egg-info` files were removed again
after the build, preserving the existing source-tree cleanup.

## Remaining scope

The overall pre-P13 goal remains active for further adversarial review, release
consistency, and evidence-based UI refinement. P13 Durable Trace / Resume and a
heavier Desktop product remain paused.
