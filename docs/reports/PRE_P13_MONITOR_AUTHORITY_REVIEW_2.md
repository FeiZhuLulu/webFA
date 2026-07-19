# Pre-P13 Monitor Authority Review — Iteration 2

Date: 2026-07-16

## Scope

P13 Durable Trace / Resume remains explicitly deferred. This iteration reviewed the current Session Monitor source, one-time Monitor Grant authentication, WebSocket lifetime, Session/Profile/runtime-generation binding, HumanControlLease authority, visual-stream cleanup, and the related regression surface.

## Findings and corrections

### 1. An active Monitor connection was not continuously bound to its Session generation

The supervisor path validated a grant when the WebSocket authenticated, but the lifetime watcher only checked grant revocation and expiry. Replacing a Session generation could therefore leave an already authenticated connection alive until another task failed or the grant expired. The router also compared Profile and generation but did not independently verify the returned Session identifier.

`MonitorGatewayRouter.validate()` now enforces the complete `(session_id, profile_id, runtime_generation)` tuple. The active grant watcher revalidates this tuple every cycle and closes the connection with code 4409 when any member changes. Existing finalization then releases HumanControlLease state, the visual stream, and the event subscription.

### 2. Invalid Monitor authentication could initialize the browser runtime

The WebSocket previously resolved or created the runtime before consuming its one-time Monitor Token. An allowed-origin client with an invalid token could not gain authority, but it could still cause an unnecessary supervisor initialization. Runtime resolution now happens only after successful token consumption. A regression test proves that an invalid token closes with code 4401 and leaves runtime state uninitialized.

### 3. A HumanControlLease could nominally outlive its Monitor Grant

HumanControlLease has a 30-second minimum duration. The previous bounding logic rounded a nearly expired grant up to that minimum, so the lease expiry could be later than the authority that created it. New takeover acquisition is now rejected when the grant has less than 30 seconds remaining; otherwise the lease is bounded by the requested duration, grant remainder, and the 1,800-second HumanControl maximum.

### 4. Session Monitor UI needs a dedicated visual iteration

The source audit found a visual-system split from the upgraded Control Center, oversized fixed sidebars at the 960-pixel minimum window, collapsed regions that can retain focusable descendants, weak empty/error differentiation, missing lease-expiry visibility, and incomplete focus/reduced-motion treatment. The required in-app visual inspection surface was unavailable during this iteration, so these findings are recorded without shipping an unverified visual rewrite. The next UI iteration must include real screenshots and interaction checks before acceptance.

## Verification evidence

- Monitor authority, HumanControl, and visual-surface regression group: 29 passed.
- Full Python suite: 524 passed, 1 skipped, 2 existing upstream `websockets` deprecation warnings.
- Active-generation replacement, invalid-token runtime initialization, complete binding-tuple validation, and lease/grant duration invariants now have explicit regression coverage.
- P13 protocol, storage, trace, and resume work was not introduced.

## Remaining work

- Implement and visually verify the Session Monitor hierarchy, responsive layout, keyboard focus containment, empty/error states, and lease-expiry feedback.
- Continue adversarial closure review across supervisor shutdown, restart races, Profile migration, packaging, and public-protocol compatibility.
- Keep P13 deferred until the current P1–P12 and Post-Core baseline is proven release-ready.
