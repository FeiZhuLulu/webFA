# Pre-P13 Profile Policy and Control Session Review — Iteration 23

Date: 2026-07-19  
Status: accepted by independent Grok review for the open-source Runtime
baseline; P13 and formal Windows Desktop release remain deferred

## Outcome

This iteration closes the remaining ambiguity between persistent Profile
identity, live authorization policy, offline browser-storage maintenance, and
the separately authenticated human control plane. It adds no Agent behavior and
does not turn Desktop into an Agent. WebFA remains the internet Runtime used by
independent external Agent clients.

The frozen P12 statement that a running Session cannot change Profile means the
Session cannot switch its Profile identity. It does not prohibit the protected
control plane from narrowing versioned Profile policy metadata. Existing P12
grant renewal intentionally rechecks current Agent bindings so revocation takes
effect on the next operation.

## Defects corrected

1. A preliminary blanket prohibition on Profile edits during an active Session
   conflicted with the accepted live-revocation contract. It was removed.
   Versioned Catalog policy updates remain live; archive, restore, Cookie,
   clone, Bundle, deletion, migration, and other identity-storage maintenance
   retain their offline mutation-lease requirements.
2. Profile policy reads and writes previously delegated through Supervisor
   compatibility behavior that could create a BrowserSession. They now use the
   persistent ProfileRepository directly and do not create Runtime authority.
3. Session-scoped control operations could be evaluated as the synthetic
   `anonymous-mcp` Agent. An Agent-bound Profile then rejected its own protected
   human control plane. Supervisor now exposes an explicit control Session path
   that creates no Agent connection, Profile Grant, or Session write lease.
4. Empty financial-policy, payment-instrument, Step-up, receipt, and local-
   resource reads could create a compatibility Session. They now return empty
   state without a Session side effect.
5. Payment registration wrote the in-memory instrument before automatically
   binding its persistent Profile financial policy. Broker preflight is now
   side-effect-free; the Profile binding completes before instrument creation,
   so a Catalog failure cannot leave a usable partially bound instrument.
6. Safety UI policy save silently replaced all `bound_agent_ids` with the
   currently displayed Agent (or cleared them) and always cleared
   `safety_policy_id`, despite exposing neither field for editing. It now
   preserves both values. Visible policy fields remain editable during an
   active Session and clearly state that narrowing takes effect on the next
   Agent operation; identity-storage maintenance is still offline.
7. A P12 local-resource grant is Session/generation scoped. The control route
   now rejects an ambiguous request that names multiple target Profiles instead
   of creating a grant that appears cross-Session but cannot be consumed there.

## Product and authority boundary

- External Agents still own MCP connections and all webpage decisions.
- A protected control Session may hold Session-scoped resource, financial,
  Step-up, receipt, or takeover state, but it has no Agent write authority.
- Profile policy updates are optimistic-versioned Catalog metadata. They do not
  take the filesystem `ProfileMutationLease` held by an active BrowserHost.
- The Session remains bound to one Profile and runtime generation. Browser
  identity storage is never modified concurrently with an active Session.
- P11 resource/payment authority remains transient and generation-bound. P13 is
  still responsible for any future durable trace or resume design.

## Development verification performed

These checks are implementation feedback, not the independent final acceptance:

- Profile, payment broker, Profile API, protected control, Supervisor authority,
  Renderer contract, and selected real payment flows: 53 passed, 10 deselected.
- Real-Chromium payment/resource/Visualizer focused run: 8 passed, 11 deselected.
- Renderer TypeScript: passed.
- Production Renderer build: passed.
- Source UI audit: passed, 12 captures.
- Original-resolution Safety desktop and 390 x 844 mobile drawer inspection:
  passed; the immediate-effect notice remains readable and the existing bounded
  scroll/modal hierarchy is preserved.
- Iteration-file `git diff --check`: passed apart from existing Windows
  line-ending notices.

At implementation handoff, no full-suite or release-candidate claim was made by
Codex. The independent results below supersede that pending status only for the
explicitly accepted open-source Runtime baseline.

## Independent Grok acceptance

Grok independently reran the iteration gates without changing product code and
accepted the current worktree as the open-source Runtime baseline:

- focused policy/control/payment/UI adversarial run: 50 passed;
- full Python suite: 679 passed, 2 skipped;
- Electron process suite: 26 passed;
- Electron and Renderer TypeScript: passed;
- Renderer build and source UI audit: passed, 12 captures;
- Python sdist and wheel build: passed for
  `webfa_desktop_runtime-0.2.0`;
- all seven adversarial handoff checks: passed;
- secret/hygiene sampling found only fake redaction fixtures.

The first full Python attempt produced 56 Chromium CDP HTTP 502 failures because
the shell inherited `HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:7897` and local
CDP discovery was proxied. Clearing both uppercase and lowercase HTTP(S) proxy
variables and setting `NO_PROXY=*` produced the accepted 679/2 result. For exact
reproduction, clear those variables before the current implementation is
hardened to bypass proxies for localhost CDP HTTP requests.

The localhost CDP proxy bypass is recorded as non-blocking future hardening; it
does not change this acceptance result. The worktree still contains many
uncommitted changes, so the result is not a commit, release, or immutable
artifact certificate. Windows installer, signing, real upgrade, clean-user, and
assistive-technology gates were not run and remain outside this baseline.

## Acceptance command reference

For a future candidate, treat its exact worktree as authoritative and rerun, at
minimum:

```powershell
python -m pytest -q
npm run test:electron-process
npm run typecheck:electron
npm run typecheck:renderer
npm run build:renderer
npm run audit:source:ui
python -m build
```

Then follow the source/wheel candidate gates in `RELEASE_CHECKLIST.md`, including
installed-wheel isolation, exact five-tool MCP smoke, public-path/secret hygiene,
and intended-diff review. Windows installer, signing, upgrade, clean-user, and
assistive-technology gates apply only when accepting a formal
Windows Desktop candidate; they do not block the open-source Runtime baseline.

Future acceptance should specifically adversarially verify:

1. an active Agent loses continued access after its Profile binding is narrowed;
2. policy metadata remains writable while ProfileProcessLock is held, while
   archive/restore/storage maintenance remains blocked;
3. protected control Session creation produces no Agent Profile Grant or Session
   write lease and cannot execute a webpage operation by itself;
4. empty control reads leave `active_session_count` at zero;
5. missing/unsupported payment policy or reference validation leaves neither a
   usable instrument nor an unintended Profile policy binding;
6. Safety policy save preserves hidden Agent-binding and safety-policy fields;
7. all 12 source UI states remain accessible, responsive, and visually coherent.

P13 Durable Trace / Resume remains out of scope. Desktop remains a lightweight
Runtime Manager rather than an Agent host, planner, model surface, memory layer,
or task orchestrator.
