# Pre-P13 Session Monitor UI Review — Iteration 3

Date: 2026-07-16

## Scope

P13 Durable Trace / Resume remains deferred. This iteration implemented the Session Monitor visual and interaction corrections identified in iteration 2, without changing Monitor permissions, the five-tool agent protocol, BrowserHost ownership, or HumanControlLease authority.

## Findings and corrections

### 1. The Monitor had diverged from the Control Center visual system

The Monitor still used a cold gray canvas, an Inter-first type stack, a purple-to-blue logo, multiple competing accent colors, pill-heavy status treatment, and generic white cards. It now shares the Control Center's warm neutral surfaces, Segoe variable typography, compact mono data labels, single teal accent, restrained amber/danger states, custom WebFA mark, focus treatment, and reduced-motion behavior. Status, actions, empty states, safety information, and the BrowserHost surface now form one hierarchy.

### 2. The minimum desktop window left too little room for the actual page

At 960 × 640, the previous fixed 270px and 340px sidebars left only 350px for the BrowserHost surface. Responsive clamped columns now resolve to 216px / 248px at that size, leaving 496px for the page with no horizontal overflow. At the normal 1280px viewport the page surface is 768px wide. Either sidebar can still collapse independently, and collapsing both yields the full 960px surface.

### 3. Collapsed panels remained in the accessibility tree and keyboard order

Zero-width sidebars previously retained their descendants while only applying `aria-hidden`. Collapsed sidebars now use the native `hidden` state and explicit CSS Grid column placement. Their controls are not rendered or keyboard reachable, while restore controls move into the surface header. Real interaction testing caught and corrected a Grid auto-placement defect where removing the first column initially moved the surface into the zero-width track.

### 4. Empty, error, and lease states were underspecified

The surface now distinguishes connection establishment, missing authorization, visual-stream failure, and ordinary frame waiting. Inline alerts use semantic live/error roles, activity has a composed empty state, and connection status uses a visible state dot. Agent Lease and HumanControlLease remaining time are shown as live countdowns in context, with active human control also reflected in the header and surface badge.

## Verification evidence

- Production-renderer visual inspection at 1280 × 720 and 960 × 640.
- Measured page-surface widths: 768px at 1280; 496px at 960; 960px with both sidebars collapsed.
- No horizontal overflow at 960px; both collapse and restore actions resolved uniquely and completed successfully.
- Both hidden sidebars present zero visible focusable descendants; visible keyboard focus ring verified.
- Production renderer console: zero errors and zero warnings.
- Renderer and Electron TypeScript checks: passed.
- Next production build: passed; `/`, `/_not-found`, and `/monitor` prerendered.
- Electron build: passed.
- Monitor/Electron focused contract and integration tests: passed; the contract now locks hidden-panel, explicit-grid, lease-visibility, focus, and reduced-motion requirements.
- Full Python suite: 524 passed, 1 skipped, 2 existing upstream `websockets` deprecation warnings.
- Live Monitor authentication, frame streaming, same-page HumanControlLease acquisition/input/release, expiry, and disconnect cleanup remain covered by the passing integration suite.

## Remaining work

- Continue adversarial review of supervisor shutdown/restart races, process cleanup, Session generation replacement, and concurrent Profile lifecycle boundaries.
- Reconcile production packaging and clean-install verification across Python and Electron artifacts.
- Continue incremental UI refinement from real runtime states while preserving scoped Monitor grants and Agent-first authority.
- Keep P13 implementation out of scope until the current baseline is release-ready.
