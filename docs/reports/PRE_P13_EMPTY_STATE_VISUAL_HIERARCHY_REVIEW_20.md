# Pre-P13 Empty-State Visual Hierarchy Review — Iteration 20

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration returned to the real Control Center and Session Monitor surfaces
and corrected two visually weak empty/error states. It did not add a feature,
new navigation area, Agent behavior, or Desktop responsibility. WebFA remains
the internet Runtime used by external Agents; Desktop remains an optional
lightweight monitoring, approval, management, and HumanControl surface.

## Baseline findings

The current production Renderer already passed overflow, labeling, dialog,
focus, and responsive gates. Original-resolution inspection nevertheless found
two hierarchy defects in the accepted baseline under
`.release/ui-audit/iteration-20-baseline-20260719`.

### Monitor connection failure was visually delayed

The Monitor surface used CSS Grid centering, but the invisible canvas frame and
the visible error card occupied separate implicit grid rows. The combined group
was centered rather than the error card, pushing the only actionable status into
the lower portion of the desktop and mobile surface. A user first saw a large
empty grid instead of the connection failure.

The canvas frame and empty/error card now share the same explicit grid cell.
The hidden canvas remains mounted for stream/control lifecycle continuity but no
longer participates as a second layout row. The error card is exactly centered
in the live page surface at both `1440x960` and `390x844`.

### Empty Action Log looked unfinished

The Control Center's dark Action Log correctly reserves space for chronological
Agent activity, but its empty state was only one low-contrast line at the upper
left. In the compact Runtime Projection drawer, this produced a large dark block
that looked uninitialized rather than deliberately empty.

The log now presents a restrained centered terminal empty state with a small
activity mark, the title `等待 Agent 活动`, and concise copy explaining that
external Agent WebFA calls and results appear in chronological order. The log is
also exposed as a named `role="log"` polite live region. Populated log rendering
and automatic scroll behavior are unchanged.

## Repeatable visual gate

`scripts/audit-source-ui.cjs` now measures the center offset between:

- Monitor empty/error state and the page surface; and
- Action Log empty state and its terminal container.

Any visible state more than two CSS pixels from either axis center fails the
source UI audit. Final evidence reports `{x: 0, y: 0}` for Monitor desktop,
Monitor mobile, both Monitor drawer captures, Control desktop Action Log, and
the compact Runtime Projection drawer Action Log.

The existing gate continues to check exact device metrics, horizontal overflow,
visible control bounds, unnamed buttons, unlabeled fields, accessibility-tree
size, drawer focus, inert background regions, dialog modality, and opaque drawer
backgrounds.

## Accepted visual evidence

Evidence is under `.release/ui-audit/iteration-20-final-20260719`. All eight
captures were visually inspected at original resolution.

Across the final set:

- exact viewports: desktop `1440x960`, compact `390x844`;
- horizontal overflow: 0;
- visible control escapes: 0;
- visible unnamed buttons: 0;
- visible unlabeled fields: 0;
- centered-state offsets: 0px on both axes wherever visible;
- compact dialogs: 4/4 modal and opaque;
- background inert regions while a drawer is open: 2; and
- drawer focus targets: the corresponding visible close button.

Screenshot SHA-256 values:

- `control-desktop.png` — `C721A8275CB84F5E5ACCA8F2BEDD60BEE14A31A13F34626E91619591DA44C2A5`
- `control-mobile.png` — `A00BB7DDC345CB7A60DFB992D806C2C3A6FB004D305334B69580CE2860A6ADA4`
- `control-mobile-left.png` — `5CED90424C4D5B443A0AF46A4DC2916FBE999784447364F31C1F40EC50EA2CFF`
- `control-mobile-right.png` — `53A68764FDDF435F1EA4F1A6C3070EA7B8331CEDC5CB6E408EA518F850CBC26B`
- `monitor-desktop.png` — `5F501293597B7D3301DB04BAE30D162924DEA89E837629496E9C3436A6254A1E`
- `monitor-mobile.png` — `D436C7228EF9EFA35B55A0EB7E8491329CA48816351259BC8E0A5D809E348532`
- `monitor-mobile-left.png` — `15D0BE2E5C68864EC4CB2B9D7B3D7B527C76F3A59277244D83C3069792F37067`
- `monitor-mobile-right.png` — `769192D3A97DF698FD44B994E56E081D7F8E789295C0ACA8D5F0623B13ED897C`

## Regression

- Source production UI audit: 8/8 captures passed.
- Renderer production build: passed for `/`, `/_not-found`, `/icon.png`, and
  `/monitor`.
- Renderer TypeScript check: passed.
- Electron TypeScript check: passed.
- Electron process/release suite: 26 passed.
- Python: 651 passed, 2 skipped; two third-party websocket deprecation warnings.
- Renderer empty-state semantic/centering contract: passed in the full suite.
- Audit script syntax and `git diff --check`: passed apart from repository-wide
  Windows line-ending notices.

This is production-Renderer source evidence, not a claim that a new immutable
installer was built. No protocol, authority, lifecycle, Profile, Session, MCP,
or HumanControl behavior changed.

## Remaining boundary

P13 Durable Trace / Resume remains deferred. Desktop expansion remains deferred.
Further UI work should continue to improve the optional control surface without
turning it into the Agent or a traditional browsing shell. The overall closure
goal remains active.
