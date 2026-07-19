# Pre-P13 Installed UI and Windows Candidate Review — Iteration 6

Date: 2026-07-18

> **Candidate baseline, not a public release declaration.** P13 Durable Trace /
> Resume remains deferred. The exact unsigned candidate reviewed here is a
> developer-preview artifact. Stable public identity, a real historical
> cross-version upgrade, production signing/timestamping, and clean standard-
> user Windows acceptance remain open release gates.

## Scope

This iteration closed the current source, packaged-runtime, installed-lifecycle,
external-MCP, and primary desktop/390px UI review for the P1-P12, Post-Core
Profile Bootstrap, and Desktop control-plane baseline. It also hardened the
cross-version upgrade harness without substituting a synthetic previous release.
No P13 protocol, trace, replay, or resume implementation was started.

## Exact candidate

- Artifact: `.release/electron/WebFA-Setup-0.2.0-x64.exe`
- Version: `0.2.0`
- Size: `112,825,918` bytes
- SHA-256: `ca04a11bdc2d36f823402b77ff5e9c1cd36e4dff3d227ac3aa3a69f0e4e9e0ad`
- Packaged identity: `name=webfa-desktop`, `productName=WebFA`, provisional
  `appId=com.webfa.desktop`
- Electron: exact `42.7.0`; the prepared Windows x64 archive matched the pinned
  SHA-256 `56ef74c90fd8d145a5b41a7d3be6e2207fcc838538f8e92a713cecce54a7d667`.
- Mode: unsigned developer preview; Authenticode publication acceptance was not
  attempted or claimed.

The artifact digest was recomputed independently after all installed tests and
matched `.release/electron/SHA256SUMS.txt`.

## Findings and corrections

### 1. Packaged ASAR asset reads emitted a Node deprecation warning

Trace-enabled installed evidence located `DEP0180` in Electron's ASAR metadata
adaptation for filesystem-stat calls. Merely changing Electron major versions did
not remove the warning in an isolated ASAR reproduction. The Renderer server now
uses a separately declared integrity-protected archive mode that reads known
assets without ASAR metadata traversal. Development and unpacked paths retain
realpath/stat symlink-escape checks. Release verification still rejects every
ASAR symbolic link, while Electron ASAR integrity and OnlyLoadAppFromAsar fuses
remain enabled.

The installed audit now launches with trace-deprecation enabled and fails on
Node/Electron warnings, Python tracebacks, unhandled JavaScript failures,
error/fatal/critical log levels, HTTP 4xx/5xx diagnostics, or launch errors. The
final candidate log check passed over 3,685 bytes with zero rejected diagnostics.

### 2. The packaged default user-data identity did not match the product contract

Without an explicit package `productName`, Electron could derive the default
application-data directory from `webfa-desktop` rather than `WebFA`. The root
package manifest now declares `productName: WebFA`, the release contract verifies
it, and the packaged manifest preserves `name=webfa-desktop`,
`productName=WebFA`, and version `0.2.0`.

### 3. Cross-version evidence did not fully prove shared Profile-data survival

The upgrade harness now reads the historical installed ASAR identity and version,
requires the same stable packaged user-data name, launches both versions against
the exact same test-owned persistent user-data tree, seeds a precise Profile
sentinel, and proves that sentinel survives installer upgrade, current Runtime
startup, and uninstall. It also compares the complete user-data bundle before and
after uninstall and removes only its owned test tree. A static cleanup-field bug
(`serverStopped` versus `rendererServerStopped`) was corrected and contract-tested.

The reusable-user-data launch path was exercised twice against the exact current
unpacked candidate and passed both times. This validates the strengthened harness
path, but it is deliberately **not** counted as the required cross-version gate:
no real previous supported WebFA installer exists in the available artifacts.

## Installed UI, MCP, and lifecycle evidence

Evidence root:
`.release/ui-audit/installed-0.2.0-20260718T093112Z/`

The real installed application completed all twelve capture steps below. Every
step reported no horizontal overflow, no out-of-bounds elements, no unlabeled
buttons, and no unlabeled fields; the screenshots were also inspected at original
resolution for clipping, typography, spacing, borders, drawer layering, takeover
state, and responsive composition.

| # | Installed state | Health |
|---:|---|---|
| 1 | Control Center overview at the desktop viewport | Pass; 355 accessibility nodes |
| 2 | Profile identity and bootstrap management | Pass; 273 accessibility nodes |
| 3 | Resource grants and safety management | Pass; 336 accessibility nodes |
| 4 | 390px Control Center with both drawers closed | Pass; 146 accessibility nodes |
| 5 | 390px Control Center drawer, inert background, and focus treatment | Pass; 263 accessibility nodes; focus restored |
| 6 | Session Monitor at the desktop viewport | Pass; 230 accessibility nodes |
| 7 | Control Center projecting the real external MCP Agent session | Pass; 505 accessibility nodes |
| 8 | Session Monitor projecting the same MCP-controlled BrowserHost | Pass; 364 accessibility nodes |
| 9 | Exact Session-scoped HumanControlLease active | Pass; 380 accessibility nodes; control state visually distinct |
| 10 | Same page returned to Agent control | Pass; 390 accessibility nodes; authority/event state restored |
| 11 | 390px live Session Monitor with sidebars closed | Pass; 52 accessibility nodes |
| 12 | 390px Monitor context drawer and inert surface | Pass; 132 accessibility nodes; focus restored |

The external MCP process used the Runtime-advertised installed sidecar, listed
exactly the five public tools, and completed
`initialize -> tools/list -> open -> observe -> act -> observe`. Desktop Runtime
ownership remained intact, and both UI surfaces projected the same Agent, Profile,
Session, document, and live BrowserHost frame.

The audit installed the candidate, used graceful `Browser.close`, uninstalled it,
and proved clean installed/runtime state. The separate installed lifecycle gate
also passed current-user installation, 223-source-file payload identity,
installed startup/quit, same-version reinstall, registry/shortcut/cache identity,
and residue-free uninstall.

## Regression evidence

- Full Python suite: `603 passed, 1 skipped`; two upstream `websockets`
  deprecation warnings remain isolated to test dependencies.
- Electron process/release suite: `23/23` passed.
- Electron and Renderer TypeScript checks: passed.
- npm production/development audit in the candidate build: zero vulnerabilities.
- Packaged ASAR, sidecar, Electron archive, hardened fuse, icon, NSIS physical
  envelope, embedded payload, and checksum verification: passed.
- Installed UI application-log validation with trace-deprecation: passed.
- `git diff --check`: passed; only checkout line-ending notices were emitted.

## Remaining release gates

- Decide and freeze the stable public `appId`; `com.webfa.desktop` remains
  provisional and must not be changed silently.
- Run the strict cross-version harness against a real previous supported
  installer and retain its Profile-sentinel evidence.
- Sign and timestamp the installer and relevant executables with the production
  certificate, then verify trust on the exact final artifact.
- Run the installed candidate as a clean standard Windows user and visually
  accept Start menu, desktop shortcut, taskbar, Tray, and uninstaller identity.
- Prove platform-default application-data placement and uninstall preservation
  in that clean installed environment.
- Extend installed visual, keyboard, and assistive-technology coverage to
  missing-browser, offline, loading, Runtime startup-failure, and recovery states.

These items gate a formal public Windows release declaration; they do not block
continued P1-P12/Post-Core maintenance or UI improvement while P13 stays paused.
