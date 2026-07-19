# Pre-P13 Runtime Initialization and Ownership Review — Iteration 14

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration made the lightweight Runtime host single-owner under concurrent
first connections. It does not add Agent behavior, planning, memory, or Desktop
orchestration: independent Agents still decide through MCP, WebFA remains the
internet Runtime, and Desktop remains an optional monitor/control surface.

## Defects reproduced

Two adversarial tests proved that Runtime lifecycle ownership could diverge:

1. Twelve concurrent first HTTP requests constructed twelve independent
   `BrowserRuntimeSupervisor` objects. Only the last assignment remained in app
   state, so an earlier request could open a BrowserHost owned by an overwritten
   Supervisor that application shutdown could no longer reach.
2. Monitor WebSocket maintained a second unprotected lazy-initialization path.
   With HTTP and Monitor connections arriving together, the controlled test
   constructed seven Supervisors even after the HTTP path itself was locked.
3. Shutdown closed only the `browser_runtime` alias. A Supervisor stored only as
   `browser_runtime_supervisor` was not closed, while naively adding both names
   would close an aliased object twice.

These were implementation defects demonstrated by failing pre-fix tests: the
first concurrent test observed 12 constructors, the cross-surface test observed
7, and the Supervisor-only shutdown test observed no close call.

## Corrections

- Every application now owns one Runtime-initialization lock.
- Runtime resolution uses double-checked locking and preserves an explicitly
  injected Supervisor while publishing one shared Runtime alias.
- HTTP, Visualizer, control routes, and Monitor WebSocket all use the same
  Runtime-resolution function; the duplicate Monitor initializer was removed.
- A process-local fallback lock keeps manually constructed test/integration apps
  safe when they do not originate from `create_app()`.
- Shutdown considers both Runtime state names, deduplicates services by object
  identity, attempts every distinct close after failures, and reports collected
  failures through the existing `ExceptionGroup` contract.

## Verification

- Focused Runtime lifecycle, multi-Session, Monitor, and Visualizer regression:
  30 passed.
- Final Python suite: 629 passed, 1 skipped, with two third-party websocket
  deprecation warnings.
- Electron and Renderer type checks passed; Electron process/release suite:
  26 passed.
- `git diff --check` passed apart from Windows line-ending notices.
- No Renderer DOM, CSS, or interaction source changed. The Desktop remains a
  lightweight Runtime Manager and now observes the same single Runtime instance
  as Agent and Monitor connections.

Artifacts under `.release/source-dist/iteration-14`:

- `webfa_desktop_runtime-0.2.0-py3-none-any.whl` — 277,851 bytes — SHA-256
  `2AC8BDF5C51C352A25C890B47D13D9F433729CA548F2F2E80E1041E07F4770EA`
- `webfa_desktop_runtime-0.2.0.tar.gz` — 238,570 bytes — SHA-256
  `2AE434A429A163E640B21149C56D6F9B660C1B0B183F3A1A82D3024E733A110A`

The wheel contains 160 entries and the sdist 195; neither includes tests or
console source. The wheel was installed into a source-invisible venv outside the
repository. Its import resolved from that venv, `pip check` and CLI version
passed, and `webfa doctor` passed Runtime health, Managed Chromium discovery,
the exact default MCP tool surface, and the local Web Object action loop using
an explicitly isolated data root.

Generated tracked `webfa_desktop_runtime.egg-info` files were removed again
after the build so the pre-existing source-tree cleanup remains intact.

## Remaining scope

The overall pre-P13 goal remains active for further adversarial maintenance,
release consistency review, and restrained UI polish. P13 Durable Trace / Resume
remains paused. Desktop expansion beyond the optional Runtime management,
monitoring, approval, and HumanControl surface remains out of scope.
