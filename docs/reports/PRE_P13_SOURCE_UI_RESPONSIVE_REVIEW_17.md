# Pre-P13 Source UI Responsive Review — Iteration 17

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration returned the closure work to the real Control Center and Monitor
surfaces. It added a repeatable production-Renderer visual gate and corrected a
compact Monitor layering defect without adding Desktop responsibilities. WebFA
remains the Agent-used internet Runtime; Desktop remains an optional lightweight
host, monitor, approval, and HumanControl surface.

## Reliable source UI audit

`npm run audit:source:ui` now:

- builds the static production Renderer before inspection;
- serves only that export on a loopback ephemeral port;
- launches local Chrome/Edge in a dedicated owned profile;
- applies exact `1440x960` and `390x844` CSS device metrics through CDP;
- captures Control Center and Monitor desktop, compact default, compact left
  drawer, and compact right drawer states;
- records horizontal overflow, visible control bounds, unnamed buttons,
  unlabeled fields, accessibility-tree size, focus target, inert regions,
  dialog modality, and computed drawer opacity; and
- fails when a visible control escapes horizontally, a field loses its label,
  a button loses its name, or a compact dialog is non-modal/translucent.

An initial exploratory Chrome command-line capture was discarded because its
window-size path cropped a wider CSS viewport into a 390px bitmap. The accepted
CDP evidence reports the actual `innerWidth` and therefore does not use that
false visual signal.

## Visual defect and correction

The accepted baseline showed no responsive overflow, but visual inspection of
the compact Monitor right drawer found that the desktop translucent sidebar
surface allowed the centered connection-error card to show through below the
management cards. This weakened hierarchy and repeated the compact Control
Center drawer defect already corrected in iteration 12.

Both compact Monitor drawers now use the opaque management background while
desktop sidebars retain their existing translucent treatment. No authority,
state, interaction, or public protocol changed.

## Accepted visual evidence

Evidence is under `.release/ui-audit/iteration-17-final-20260719`.

All eight captures passed with:

- exact viewports: desktop `1440x960`, compact `390x844`;
- horizontal overflow: 0;
- visible control escapes: 0;
- visible unnamed buttons: 0;
- visible unlabeled fields: 0;
- compact dialogs: 4/4 `aria-modal=true` and opaque;
- compact drawer background: `rgb(241, 239, 232)`;
- background inert regions while each drawer is open: 2;
- drawer focus targets: the corresponding visible close button; and
- accessibility trees ranging from 59 to 263 nodes.

Screenshot SHA-256 values:

- `control-desktop.png` — `5F6FBDD7A959B461E40BE6973900282AD0675C48A23186003555AAAEF79D4D28`
- `control-mobile.png` — `A00BB7DDC345CB7A60DFB992D806C2C3A6FB004D305334B69580CE2860A6ADA4`
- `control-mobile-left.png` — `5CED90424C4D5B443A0AF46A4DC2916FBE999784447364F31C1F40EC50EA2CFF`
- `control-mobile-right.png` — `C9A75E8ACE8B5011846F3949AC72CEA7A238B8ED1B995499B8E7DDC8A26A1027`
- `monitor-desktop.png` — `7751234B03BD3E717775D15B00B6AA9B7A99BAFE46FEBD5009DC01572756667F`
- `monitor-mobile.png` — `9E8916ED673B612F90E685A53E6543E72D6C5109D85544872E00BC99F5C0C6B1`
- `monitor-mobile-left.png` — `99559770435497B0E27C21A37902A3CDCDCE5CEC7564B6B5CD17AA8A4C677D74`
- `monitor-mobile-right.png` — `98DA04A38B2165AA3161229788DD09997DE6127FDCBDD288236DD66825D6ADAC`

All eight final screenshots were visually inspected at original resolution.

## Regression

- Production Renderer build passed for `/`, `/_not-found`, `/icon.png`, and
  `/monitor` on every accepted visual run.
- Renderer and Electron TypeScript checks passed.
- Electron process/release suite: 26 passed.
- Final Python suite: 638 passed, 1 skipped, with two third-party websocket
  deprecation warnings.
- Audit script syntax and `git diff --check` passed apart from Windows line-
  ending notices.

This is source-candidate visual evidence, not a claim that a new installer was
built or installed. The existing installed keyboard/HumanControl gates remain
covered by the prior installed audit; the final immutable Desktop candidate must
rerun the installed audit after the remaining closure work is frozen.

## Remaining scope

The overall pre-P13 goal remains active for further adversarial maintenance,
final release consistency, installed-candidate UI verification, and restrained
visual refinement. P13 Durable Trace / Resume and heavier Desktop functionality
remain paused.
