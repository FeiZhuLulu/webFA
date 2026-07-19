# Pre-P13 Installed Sidecar Failure and Recovery Review — Iteration 8

Date: 2026-07-18

> **Unsigned developer-preview evidence, not a public release declaration.**
> P13 Durable Trace / Resume remains deferred.

## Outcome

The installed-candidate review now closes the locally provable missing sidecar,
corrupt sidecar, real process spawn failure, startup-timeout cleanup, and exact
repair/recovery gaps. The work added no product failure-injection switch and did
not change the packaged product inputs. The already-audited candidate remained:

- Artifact: `.release/electron/WebFA-Setup-0.2.0-x64.exe`
- Size: `112,816,653` bytes
- SHA-256: `8cf4ce444ffdae96f950e7d1ac0896b36f6dc0d7bd5934448903bbc0bf4fc52a`
- Mode: unsigned Windows x64 developer preview

## Failure harness and restoration contract

After the normal installed MCP flow completed, the audit moved the exact
installed `resources/sidecar/webfa.exe` to an audit-owned directory and verified
that backup against the Runtime-advertised MCP command SHA-256
`7c735f5e136ad3ef24b85c0994d37b5eb02a4b1bbbf5d932b84cbb843505bb00`.
It then exercised three real Windows launch paths:

1. The executable was absent. Desktop reported `spawn_failed`, held no Runtime
   authority, exposed no PID, and presented a bounded recovery surface.
2. The executable was a corrupt regular file. Desktop again reported
   `spawn_failed` with no authority or PID, including at the 390px layout.
3. The executable was a valid audit-built Windows process that slept without
   serving the Runtime health identity. The real 20-second deadline produced
   `startup_timeout`; Desktop reaped its owned process before presenting the
   fault and retained no control token.

The audit removed every injected file, restored the original sidecar by rename,
recomputed the same SHA-256, launched the installed Desktop again, and observed
`state=running`, `ownership=desktop`, release `0.2.0`, protocol `1`, and a fresh
Runtime instance identity. The audit-owned harness directory, Runtime data,
browser-discovery isolation tree, installed application, registry state,
shortcuts, updater cache, and owned processes were all removed.

## Installed UI and log evidence

Evidence root:
`.release/ui-audit/installed-0.2.0-20260718T123721Z/`

The final audit passed all 24 captures. The original 20 normal, Agent,
HumanControl, responsive, stop/disconnect, collision/recovery, and missing-browser
states remained accepted. Four new original-resolution images were inspected:

| # | Installed state | AX nodes |
|---:|---|---:|
| 21 | Installed sidecar missing | 280 |
| 22 | Corrupt installed sidecar at 390px | 81 |
| 23 | Real process startup timeout after owned cleanup | 279 |
| 24 | Exact sidecar restored and Runtime healthy again | 283 |

Across all 24 images the minimum accessibility-tree size was 52 nodes. There
were zero horizontal-overflow states, viewport-crossing visible elements,
unnamed visible buttons, unlabeled visible fields, visible error toasts, or raw
fetch-failure text. The three new fault surfaces exposed no install path,
sidecar path, `ENOENT`, `spawn` diagnostic, token, or traceback.

Application-log validation checked 9,201 bytes. Baseline, missing-browser,
startup-timeout, and repaired-sidecar scenarios had no rejected warning/error
diagnostics. Missing and corrupt sidecar scenarios each emitted exactly one
expected local spawn diagnostic and no unexpected warning, traceback, IPC,
HTTP, Chromium, wrapper, or cleanup failure.

Two preliminary audit attempts were rejected before acceptance: one exposed an
over-broad harness check that confused the UI policy label `Unknown` with a raw
Windows error, and one exposed a non-converged CDP viewport override. Both runs
proved restoration and residue-free cleanup. The final harness now retries and
verifies the exact viewport dimensions rather than weakening responsive checks.

## Regression evidence

- Python: `606 passed, 1 skipped`; two upstream `websockets` deprecation warnings.
- Electron process/release suite: `26/26` passed, including an explicit startup
  timeout ownership/token cleanup test.
- Electron and Renderer TypeScript checks: passed.
- Desktop distribution contract: `16/16` passed.
- Installed UI audit: `24/24` accepted with log validation passed.
- Independent unsigned install/reinstall/uninstall smoke: passed, including
  exact payload/installer identity stability and complete residue cleanup.
- `git diff --check`: passed with checkout line-ending notices only.

## Remaining formal release gates

- Freeze the stable public `appId`; `com.webfa.desktop` remains provisional.
- Run the strict upgrade harness against a real previous supported installer.
- Complete keyboard-only and assistive-technology testing; screenshots and AX
  trees are not a WCAG compliance claim.
- Accept installation, shell surfaces, metadata, application-data placement,
  and uninstall preservation as a clean standard Windows user.
- Sign and timestamp the final executables and installer, then rerun the entire
  installed lifecycle, 24-state UI, and sidecar failure/recovery sequence against
  that exact immutable signed artifact.

These external gates still prevent a formal public Windows release declaration.
They do not block continued P1-P12/Post-Core maintenance and UI refinement while
P13 remains paused.
