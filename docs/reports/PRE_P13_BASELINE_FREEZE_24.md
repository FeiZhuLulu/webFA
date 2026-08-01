# Pre-P13 Baseline Freeze — UI, Brand, and Source/Wheel Re-verification

Date: 2026-08-02 (+08:00)

Status: phase complete; the current pre-P13 source baseline is ready to be
committed; P13 implementation and formal Windows Desktop release remain
deferred.

## Scope

This closure pass reviewed and re-baselined the post-2026-07-19 UI and brand
work without changing the five-tool Agent protocol, WebFA object model,
Profile/Session authority, or Runtime lifecycle contracts.

- The Control Center and Session Monitor use the shared visual token layer and
  the reusable `BrandMark` component.
- `packaging/webfa-mark.svg` is the checked-in brand geometry master; the asset
  generator fails closed if its rasterizer geometry diverges from that master.
- The 12 production-Renderer UI captures under `tests/ui-baseline/` are the
  accepted Windows + Segoe UI Variable reference set.
- README wording now describes Step-up as policy-triggered, retains the unknown
  GET/navigation side-effect boundary, and links the current readiness and
  release evidence.
- The repository-local `.progress/` coordination directory is ignored and is
  not part of the release/source candidate.

## Asset reproducibility

`npm run generate:brand-assets` was run repeatedly from the same source. Every
recorded run passed the Windows ICO validator and produced identical hashes:

| Asset | SHA-256 |
| --- | --- |
| `packaging/webfa.ico` | `E599348CA05E8002F41DA5D1A98FD4C019FF9517ABC8D6A5CA9A4FD417D4D449` |
| `apps/desktop/renderer/src/app/icon.png` | `FCC5F22FB62EF6063F21075FF434D61EF188CDC38C40246E9609C2BCCA4E26B2` |

## Verification

All gates below were rerun during this closure pass. The full Python suite and
source UI audit were repeated after the audit-settle correction described in
the next section.

- `python -m pytest -q` — **681 passed, 2 skipped, 2 warnings**.
- `npm run test:electron-process` — **26 passed, 0 failed**.
- `npm run typecheck:renderer` — passed.
- `npm run typecheck:electron` — passed.
- `npm run build:renderer` — passed; `/` and `/monitor` statically exported.
- `npm run audit:source:ui` — passed; **12/12 captures**, no layout/accessibility
  failures, and all 12 visual diff ratios were `0` against the checked-in
  baseline.
- `python -m build` — passed; wheel and sdist produced.
- Source-external wheel smoke — passed in a temporary venv with source paths
  cleared: `pip check`, installed import-location probe, `webfa doctor`, and
  `initialize -> tools/list -> open -> observe -> act -> observe` through the
  installed `webfa-mcp` entry point all passed. The exact installed MCP tool set
  remained `webfa.open_url`, `webfa.observe`, `webfa.act`, `webfa.get_tabs`, and
  `webfa.switch_tab`.

Current build artifact hashes (candidate-local, not publication checksums):

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `dist/webfa_desktop_runtime-0.2.0-py3-none-any.whl` | 278,655 bytes | `60188C722CE85698E979D6CCE1E4918860733BB344100CAC9E886D520689CFD7` |
| `dist/webfa_desktop_runtime-0.2.0.tar.gz` | 235,943 bytes | `57BC6F6364A1521D29DC2E0CE8EF1DC368C9191181A06FCDB41005351CB4607C` |

## Contract and audit corrections

The README rewrite replaced the former optional-desktop paragraph with a
dedicated `## 开发` / `## Development` section. The existing packaging contract
still searched for the retired paragraph and therefore treated the entire
README as the source-install section. The contract now uses the current section
heading as its boundary; the source install remains proven independent of
`npm install`.

The source UI auditor previously relied on a fixed 3.2-second delay. On a cold
control-page load it could capture the server-rendered `starting` state before
the initial Runtime probe settled, while the later mobile captures already
matched the stopped-state baseline. The auditor now waits for the visible
Runtime state to leave that transient state and fails clearly if it cannot;
the 12 checked-in baselines were not rewritten.

## Remaining boundaries

This is an open-source Runtime/source baseline, not a formal Windows release
certificate. Stable public `appId`, a real previous-version upgrade, clean-user
installed-shell validation, complete keyboard/assistive-technology acceptance,
Authenticode signing/timestamping, and final publication checksums remain
unchecked in `RELEASE_CHECKLIST.md`. P13 Durable Trace / Resume remains future
scope and must not be implied by this baseline.

## Next handoff

With this baseline frozen, the next product phase is to write and review the
complete P13 Durable Trace / Resume target architecture before implementing any
P13 storage, protocol, or replay code.
