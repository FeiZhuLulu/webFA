# Pre-P13 Keyboard, Focus, and Responsive Closure Review — Iteration 9

Date: 2026-07-18  
Scope: P1–P12, Post-Core Profile Bootstrap, and Desktop control surface closure  
P13 Durable Trace / Resume remains deferred.

## Candidate reviewed

The accepted development candidate is the unsigned Windows x64 installer:

- path: `.release/electron/WebFA-Setup-0.2.0-x64.exe`
- bytes: `112810056`
- SHA-256: `01a11ea34b8875f1611a44020b22134ed40a89aaa047a808fad012e5fa4ec278`

The production packaging entry completed from a fresh dependency install with
`0 vulnerabilities`. This unsigned artifact is development evidence only and is
not a formal public release.

## Product findings closed

The review found that HumanControl page keyboard capture had no local keyboard
escape path. Escape now returns focus to a visible **Page Keyboard** control
without releasing the Session-scoped lease; Enter or Space re-enters page
capture, Tab reaches **Return to Agent**, and focus returns to the takeover
button when the lease or connection ends.

The review also closed three adjacent defects:

1. HumanControl acquisition could try to focus its textarea before React had
   rendered it. Focus is now driven by the active-state render lifecycle.
2. Return to Agent was incorrectly disabled when the visual frame temporarily
   disappeared. An active connected lease can now always be returned; only new
   acquisition requires a current frame.
3. Compact Monitor layout permanently collapsed both desktop sidebars, and
   reopening one desktop sidebar collapsed the other. Compact drawers remain
   mutually exclusive, while desktop sidebar state is independent and restored
   when leaving compact layout.

Known takeover reasons are now shown as user-facing labels (`身份确认`,
`身份验证`, `不透明页面`) instead of raw underscore-delimited identifiers, which
keeps the 390px status footer readable.

## Deterministic installed acceptance

The final evidence is
`.release/ui-audit/installed-0.2.0-20260718T135310Z/audit-evidence.json`.
It passed all 25 captures. Every image was visually reviewed.

The keyboard record proves:

- both skip links are the first visible keyboard stop and move focus to their
  intended main surface;
- compact Control Center and Monitor drawers trap focus, wrap in both
  directions, make the background inert, close on Escape, and restore focus;
- desktop and 390px HumanControl can be acquired, escaped to local controls,
  re-entered, and returned to Agent entirely by keyboard;
- the active-lease return action remains enabled independently of visual-frame
  availability;
- endpoint collision, missing browser, missing sidecar, corrupt sidecar, and
  startup-timeout recovery actions are keyboard reachable with a visible 2px
  focus indicator; and
- both Monitor sidebars return after the viewport leaves compact layout.

The real external MCP probe now uses an explicit ready/release handshake. Its
stdio Session stays alive while Control Center, Monitor, and HumanControl are
examined, then exits cleanly. This removed a former audit race in which the Agent
could disconnect before UI polling observed its active lease.

Across the 25 accepted states:

- minimum accessibility-tree size: `52` nodes;
- horizontal overflow or viewport escapes: `0`;
- visible unnamed buttons: `0`;
- visible unlabeled fields: `0`;
- lingering visible error toasts: `0`;
- application-log validation: passed across `9232` checked bytes;
- installed sidecar restored, failure harness removed, uninstall clean, Runtime
  data removed, and browser-isolation data removed: all true.

One failed run against the same final candidate is intentionally retained at
`.release/ui-audit/installed-0.2.0-20260718T134744Z/`: the MCP operation passed,
but the pre-handshake harness missed the already-disconnected Agent projection.
Earlier exploratory failures exposed the render-focus race, frame-dependent
release defect, and an overly strict compact-layout wait predicate; they were
not accepted as evidence.

## Regression result

- Python: `606 passed, 1 skipped` (`3` existing third-party deprecation warnings).
- Electron process/lifecycle: `26/26` passed.
- Renderer and Electron TypeScript: passed.
- Frozen onedir sidecar and real MCP flow: passed.
- Installed unsigned lifecycle/reinstall/uninstall smoke: passed.
- Final installed UI audit: `25/25` passed.

## Gates still open

This iteration closes the locally provable critical keyboard and responsive
paths, not the formal release:

- confirm the public `appId` and visible Windows shell metadata/icon behavior;
- run on a clean standard-user VM;
- perform a real upgrade from a previous supported installer;
- finish keyboard coverage for remaining forms and management flows and conduct
  real assistive-technology acceptance; and
- sign and timestamp Desktop, sidecar, and NSIS artifacts, then rerun every
  installed gate against that exact immutable signed candidate.

P13 remains paused.
