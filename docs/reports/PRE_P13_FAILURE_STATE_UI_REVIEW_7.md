# Pre-P13 Failure-State UI and Installed Candidate Review — Iteration 7

Date: 2026-07-18

> **Unsigned developer-preview baseline, not a public release declaration.**
> P13 Durable Trace / Resume remains deferred. Stable public identity, a real
> historical cross-version upgrade, clean standard-user Windows acceptance, and
> production signing/timestamping remain formal release gates.

## Scope

This iteration completed a failure-state and recovery review across the P1-P12,
Post-Core Profile Bootstrap, Electron Desktop lifecycle, Control Center, Session
Monitor, installed MCP entry, and Windows installer. No P13 trace, replay, or
resume surface was added.

## Exact candidate

- Artifact: `.release/electron/WebFA-Setup-0.2.0-x64.exe`
- Version: `0.2.0`
- Size: `112,816,653` bytes
- SHA-256: `8cf4ce444ffdae96f950e7d1ac0896b36f6dc0d7bd5934448903bbc0bf4fc52a`
- Identity: `name=webfa-desktop`, `productName=WebFA`, provisional
  `appId=com.webfa.desktop`
- Mode: unsigned Windows x64 developer preview

The digest above was recomputed from the final installer after packaging and
again after installed UI and lifecycle verification.

## Corrections made

1. Desktop Runtime failures now cross IPC as bounded `RuntimeIssue` values with
   explicit issue codes and recovery actions. Raw child stderr, tracebacks, file
   paths, and private diagnostic text remain in local logs rather than renderer
   status.
2. The primary page surface distinguishes startup, connection verification,
   unreachable Runtime, graceful stop, endpoint collision, recovery, and missing
   browser prerequisites. It no longer describes an unavailable Runtime as
   “waiting for the Agent to open a page,” and stale visualizer state is cleared
   whenever protected refresh fails.
3. Expected Monitor unavailability no longer throws through Electron IPC.
   `monitor:getConfig` returns structured `waiting` or `unavailable` state, so a
   graceful Runtime stop does not emit `Error occurred in handler` diagnostics.
4. Monitor socket closure invalidates the decoded frame, frame count, Session
   snapshot, HumanControl state, and canvas projection. The disconnected surface
   now says there is no real-time page and cannot retain a “live projection”
   label over stale pixels.
5. Hidden Control Center sections no longer mount protected API consumers before
   they are selected. Component errors pass through the localized UI error
   boundary, eliminating a transient raw `Failed to fetch` toast found during
   original-resolution mobile review.
6. Windows Chromium discovery derives Chrome/Edge candidates from supported
   environment install roots, including per-user locations, rather than
   unconditional hard-coded system paths. This enabled a real missing-browser
   installed test without a product test backdoor.
7. Windows descendant cleanup invokes the qualified System32 `taskkill.exe`
   rather than trusting `PATH`, including under hostile inherited environments.
8. Public `/health` storage output is reduced to readiness/persistence metadata;
   absolute data, database, and log paths are no longer exposed on the
   unauthenticated loopback endpoint.

## Installed UI evidence

Evidence root:
`.release/ui-audit/installed-0.2.0-20260718T121339Z/`

The exact installed candidate completed all twenty captures below. Every step
had zero horizontal overflow, zero viewport-crossing visible elements, zero
unnamed visible buttons, zero unlabeled visible fields, zero visible error
toasts, no raw fetch-failure text, and a non-empty accessibility tree. All twenty
PNG files were inspected at original resolution.

| # | Installed state | AX nodes |
|---:|---|---:|
| 1 | Runtime identity/control verification startup boundary | 262 |
| 2 | Control Center overview | 283 |
| 3 | Profile identity and bootstrap management | 209 |
| 4 | Resource grants and safety management | 328 |
| 5 | 390px Control Center, drawers closed | 74 |
| 6 | 390px Control Center drawer, inert background and restored focus | 191 |
| 7 | Session Monitor waiting state | 230 |
| 8 | Control Center projecting the external MCP Agent Session | 433 |
| 9 | Monitor projecting the same MCP-controlled BrowserHost | 364 |
| 10 | Exact Session-scoped HumanControlLease active | 380 |
| 11 | Same page returned to Agent control | 390 |
| 12 | 390px live Monitor, drawers closed | 52 |
| 13 | 390px Monitor context drawer and inert surface | 132 |
| 14 | Control Center after graceful Runtime stop | 270 |
| 15 | Monitor disconnected with stale projection removed | 74 |
| 16 | Incompatible endpoint collision refused without attachment | 279 |
| 17 | 390px endpoint-collision recovery surface | 276 |
| 18 | Runtime recovered after endpoint release | 77 |
| 19 | Missing browser with all supported discovery roots isolated | 302 |
| 20 | 390px missing-browser prerequisite surface | 82 |

The application-log validator checked 5,440 bytes with trace-deprecation enabled
and found zero Node/Electron warnings, Python tracebacks, JavaScript unhandled
failures, Runtime or Chromium error/fatal levels, HTTP error responses, or launch
errors. Drawer focus restoration passed on both Control Center and Monitor.

## MCP and lifecycle evidence

The installed Runtime-advertised sidecar exposed exactly the five public tools
and completed `initialize -> tools/list -> open -> observe -> act -> observe`.
The external MCP connection preserved Desktop Runtime ownership and produced the
same Agent/Profile/Session/document projection in Control Center and Monitor.

The independent installed lifecycle smoke passed current-user installation,
223 source-payload files plus two install-time files, installed startup/quit,
same-version reinstall with stable payload and installer identity, and complete
program/registry/shortcut/updater-cache/process cleanup after uninstall.

## Regression evidence

- Python: `606 passed, 1 skipped`; two upstream `websockets` deprecation warnings
  remain isolated to test dependencies.
- Electron process/release: `25/25` passed.
- Renderer and Electron TypeScript checks: passed.
- Production Renderer build and complete unsigned Windows packaging: passed.
- Installed UI audit: `20/20` captures and zero deterministic UI violations.
- Installed lifecycle smoke: passed.
- `git diff --check`: passed with checkout line-ending notices only.

## Remaining formal release gates

- Freeze the stable public `appId`; `com.webfa.desktop` remains provisional.
- Run the strict upgrade harness against a real previous supported installer.
- Exercise missing/corrupt sidecar, real spawn failure, and startup-timeout states
  on the final signed candidate.
- Complete keyboard-only and assistive-technology testing; DOM/AX evidence and
  screenshots are not a WCAG compliance claim.
- Accept install, Start menu, desktop shortcut, taskbar, Tray, metadata, default
  application-data placement, and uninstall preservation as a clean standard
  Windows user.
- Sign and timestamp the final executables and installer, then rerun all
  installed lifecycle and UI evidence against that exact immutable artifact.

These gates prevent a formal public Windows release declaration. They do not
block continued P1-P12/Post-Core maintenance and UI refinement while P13 remains
paused.
