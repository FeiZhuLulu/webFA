# Pre-P13 Runtime Lifespan and Profile Singleton Review — Iteration 15

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration completed the Runtime host ownership correction by making
shutdown exception-safe and every lazy Runtime/Profile service single-owner.
The change remains below the Agent contract: WebFA is the internet Runtime,
external Agents own decisions through MCP, and Desktop remains only an optional
monitoring, approval, takeover, and Runtime-management surface.

## Defects reproduced

Adversarial lifecycle and concurrency tests proved three additional defects:

1. Raising from the host context at the lifespan `yield` skipped all code after
   the yield, so Runtime services were not closed.
2. Calling shutdown twice closed the same Profile and Browser services twice,
   because closed objects remained published in application state. A re-entered
   embedded App could therefore hand out an already-closed service.
3. Profile Repository, Storage Manager, Bootstrap, and Bundle used independent
   unprotected lazy publication. Twelve simultaneous first Profile requests
   created 12 Storage Managers, 6 Bootstrap services, and 6 Bundle services.
   In-memory preview/commit state could be published to one request and then
   overwritten by another service instance.

All three cases failed before the correction. The instance counts above are
from the controlled pre-fix concurrency run.

## Corrections

- Lifespan shutdown now runs in `finally`, including exceptional host exits.
- Every published closable service reference is revoked before close begins.
  Shutdown remains best-effort across distinct services, deduplicates aliases by
  object identity, is idempotent, and cannot republish a closed object.
- `create_app()` now owns one re-entrant service-initialization lock shared by
  Browser, HTTP control routes, Monitor WebSocket, Profile Repository, Profile
  Storage, Bootstrap, and Bundle publication.
- Each lazy getter uses a fast-path check followed by a locked second check.
  The re-entrant lock permits Bootstrap/Bundle construction to resolve their
  nested Repository and Storage dependencies without deadlock.
- Fallback locks preserve safe behavior for manually assembled integration apps.

## Verification

- Focused Runtime lifecycle, Profile, multi-Session, and Monitor regression:
  32 passed.
- Final Python suite: 632 passed, 1 skipped, with two third-party websocket
  deprecation warnings.
- Electron and Renderer type checks passed; Electron process/release suite:
  26 passed.
- `git diff --check` passed apart from Windows line-ending notices.
- No Renderer DOM, CSS, or interaction source changed. Desktop remains a thin
  Runtime Manager and does not gain Agent planning or orchestration behavior.

Artifacts under `.release/source-dist/iteration-15`:

- `webfa_desktop_runtime-0.2.0-py3-none-any.whl` — 278,192 bytes — SHA-256
  `C14996D0DD1C0F39C2151C7A61E128BE5F809EE32C58619C925F4AC9995122E5`
- `webfa_desktop_runtime-0.2.0.tar.gz` — 238,988 bytes — SHA-256
  `1D79B5AC7E9B53F42142488DD2BCA4C0225AE16C07AF7E6986E0492BD7BA4EE2`

The wheel contains 160 entries and the sdist 195; neither includes tests or
console source. The wheel was installed into a source-invisible venv outside the
repository. Its import resolved from that venv, dependency and CLI version
checks passed, and `webfa doctor` passed Runtime health, Managed Chromium,
default MCP tools, and the local Web Object action loop against an explicitly
isolated data root.

Generated tracked `webfa_desktop_runtime.egg-info` files were removed again
after the build, preserving the existing source-tree cleanup.

## Remaining scope

The overall pre-P13 goal remains active for further adversarial maintenance,
release consistency, and restrained UI refinement. P13 Durable Trace / Resume
and a heavier Desktop product remain paused.
