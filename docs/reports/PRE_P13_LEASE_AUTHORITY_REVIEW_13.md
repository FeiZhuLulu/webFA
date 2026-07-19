# Pre-P13 Lease and Connection Authority Review — Iteration 13

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration corrected the P12 connection-authority lifecycle without adding
tools or Desktop responsibilities. Independent external Agents still own their
decisions and MCP connections; WebFA remains the internet Runtime; Desktop only
projects and manages Runtime state.

## Defects reproduced

Controlled-clock and multi-connection tests proved five defects in the existing
implementation:

1. An active Profile Grant did not renew on successful use and failed after its
   original 30-minute deadline even while the connection remained active.
2. The connection-exclusive Session Lease did not renew on `act`, `observe`, or
   `get_tabs`; `WEBFA_AGENT_LEASE_TTL_SECONDS` configured only the retired inner
   compatibility lease, not the P12 Session Lease.
3. A second connection using the same Agent ID could first observe the active
   Session and then switch a guessed local tab ID such as `tab_1`, bypassing the
   outer connection-exclusive lease.
4. Changing a Profile's `bound_agent_ids` in the protected control plane did not
   invalidate continued use of an already-issued in-memory Profile Grant.
5. WebState, Monitor, and Control Center status projected the inner single-
   browser AgentLease deadline instead of the P12 connection-scoped Session
   Lease, so displayed authority could disagree with enforced authority.

The pre-fix focused run failed all five corresponding adversarial cases. These
were observable implementation defects, not documentation-only discrepancies.

## Corrections

- Successful Profile Grant checks now re-read and validate the current Profile
  catalog/binding policy, preserve grant identity and issue time, bind the
  current policy version, and renew expiry.
- Successful owned Session activity renews lease expiry while preserving lease
  ID, issue time, Agent, connection, Profile, Session, and Runtime generation.
  Expired leases are removed and read activity cannot resurrect them.
- The P12 Session Lease uses the documented
  `WEBFA_AGENT_LEASE_TTL_SECONDS` setting.
- Session write checks now validate Profile and Runtime generation in addition
  to Agent, connection, and Session.
- The local-tab fallback in `switch_tab` now requires the same outer Session
  Lease as global routed tab IDs, closing the same-Agent second-connection
  bypass.
- Supervisor WebState, status, Session summaries, and Monitor snapshots project
  the active outer Session Lease consistently. Compatibility state is retained
  only when no P12 lease exists.

## Verification

- Focused lease/routing/Supervisor/Monitor/Visualizer regression: 50 passed.
- Final Python suite: 625 passed, 1 skipped, with two third-party websocket
  deprecation warnings.
- Source distribution build completed successfully from the sdist path.
- `git diff --check` passed apart from existing Windows line-ending notices.
- No Renderer DOM/CSS/interaction source changed in this iteration. UI impact
  is limited to receiving the correct enforced lease identity and deadline, and
  is covered through Supervisor, Monitor, and Visualizer API tests.

Artifacts under `.release/source-dist/iteration-13`:

- `webfa_desktop_runtime-0.2.0-py3-none-any.whl` — 277,615 bytes — SHA-256
  `1C9B971B30F6B0AA1CE402F65C34610A09642AB48143B3929F6FB102F69A9080`
- `webfa_desktop_runtime-0.2.0.tar.gz` — 238,330 bytes — SHA-256
  `E949637AA0CD4226A32CD1122EF1E037C4E3BA109006D87F34E312792CCD382D`

The wheel contains 160 entries and the sdist 195. Neither contains tests,
`.git`, `.progress`, `node_modules`, `.release`, or `.verification`; the wheel
contains the corrected `browser/session_routing.py`.

The wheel was installed outside the source tree into a source-invisible venv
using the already available dependency set. `pip check`, import-location
isolation, CLI version, Runtime health, Managed Chromium discovery, exact
five-tool surface, and the local Web Object browser loop all passed through
`webfa doctor`. A first local smoke attempt used the shell HOME variable instead
of the intended isolated data variable and was discarded; the accepted rerun
asserted the exact project-local `.verification` data root before recording the
pass.

## Remaining scope

The overall pre-P13 goal remains active for further adversarial maintenance and
release consistency work. P13 Durable Trace / Resume remains paused. Desktop
work remains limited to defects, accessibility, clarity, and visual polish on
the lightweight Runtime Manager surface.
