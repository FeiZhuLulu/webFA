# Pre-P13 Lifecycle and Process Review — Iteration 4

Date: 2026-07-16

## Scope

P13 Durable Trace / Resume remains deferred. This iteration adversarially reviewed Session teardown, supervisor failure isolation, Profile reopen races, application lifespan cleanup, Electron child-process ownership, and actual operating-system process-tree termination. It did not change the public agent protocol, Monitor authority model, or P13 architecture.

## Findings and corrections

### 1. One failed Session close could abandon the rest of supervisor shutdown

`BrowserRuntimeSupervisor.close()` previously stopped at the first `runtime.close()` exception while already marking the supervisor closed, leaving later Session workers, Profile mutation locks, and local resources without a retry path. Shutdown now isolates failures per Session, records safe failure state where possible, finalizes every entry, and continues through the complete Session set.

### 2. A crashed runtime could lose supervisor ownership while its worker remained alive

The crash terminal path previously removed the Session entry and released its Profile lock without first closing the runtime worker and resources. Audit-write failure could also interrupt terminal cleanup. Crash handling now performs best-effort runtime closure before releasing worker, local-resource, event-bus, and Profile ownership; event-recording failure cannot prevent cleanup. Worker close jobs also terminate in `finally`, including when the browser driver's close operation fails.

### 3. Concurrent Profile reopen could recover a Session that was still closing

Session close and supervisor lookup were not one atomic lifecycle boundary. A concurrent reopen could observe and reuse the old entry before finalization. Close/finalize now remains under the supervisor lifecycle lock; reopen waits and receives a new Session ID and runtime generation after the old Session is fully terminal.

### 4. Runtime lifespan cleanup stopped after the first service failure

Application shutdown previously closed Profile Bootstrap, Profile Bundle, and Browser Runtime sequentially in a way that allowed the first exception to skip later owners. Lifespan cleanup now attempts all registered services and reports the accumulated failures only after every cleanup attempt.

### 5. Electron process managers had restart, stale-event, and duplicate-child races

The managers could start a replacement while an errored-but-live child still existed; delayed exit/error events from the old child could then overwrite the new process state. Stop/restart is now serialized and awaited, a live child handle blocks duplicate start regardless of display status, and callbacks mutate state only when they belong to the current child.

### 6. Desktop exit did not prove descendant-process cleanup

Runtime and MCP shutdown previously signalled only the direct child and Electron did not wait for termination before quitting. Both managers now own a process group/tree, use Windows `taskkill /t` or POSIX group signals with a bounded escalation path, and preserve the child handle if termination fails. Electron's first quit request now waits for both process owners to settle before allowing the final quit.

### 7. Runtime readiness and MCP logging did not match real stdio behavior

Uvicorn normally announces readiness on stderr, so the runtime could remain stuck in `starting`. Readiness is now recognized on either stream. MCP stdout is still drained to prevent backpressure but is no longer copied into desktop logs, avoiding accidental persistence of JSON-RPC payloads or sensitive tool data.

## Verification evidence

- Supervisor, lifespan, multi-Session, managed-Chromium, and Monitor integration set: 44 passed.
- Electron process lifecycle suite: 4 passed, including a real parent plus descendant process-tree termination test.
- Additional focused lifecycle/contracts set: 18 passed.
- Electron build and Electron TypeScript check: passed.
- `git diff --check`: passed; only existing LF-to-CRLF checkout notices were emitted.
- Full Python suite: 530 passed, 1 skipped, with 2 existing upstream `websockets` deprecation warnings.
- Regression coverage now proves failure-isolated supervisor close, dead crash workers, reacquirable Profile locks, generation replacement after concurrent reopen, all-service lifespan cleanup, stale-event isolation, restart ordering, and sensitive MCP stdout suppression.

## Remaining work

- Reconcile production packaging and clean-install/start-stop verification across Python, Chromium, Electron, and platform-specific artifacts.
- Review desktop MCP stdio ownership and distribution behavior as a product boundary, beyond the logging and lifecycle corrections in this iteration.
- Continue UI refinement against real runtime, failure, empty, approval, and takeover states without weakening scoped authority.
- Keep P13 implementation out of scope until the P1–P12/Post-Core baseline is release-ready.
