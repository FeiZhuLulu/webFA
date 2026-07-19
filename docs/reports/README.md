# WebFA Reports Index

The files in this directory are point-in-time engineering evidence. They do not
override the current code, automated tests, public documentation, or release
checklist, and an older passing report is not a release certificate for a new
artifact.

## Current reading order

For the current product and release state, read these sources in order:

1. `README.md` or `README.en.md` — public product contract and supported entry
   points.
2. `docs/OPEN_SOURCE_READINESS.md` and `SECURITY.md` — current readiness and
   trust boundaries.
3. `RELEASE_CHECKLIST.md` — gates that must be rerun for an exact candidate.
4. `docs/browser-runtime-roadmap.md` — completed Runtime evolution and deferred
   future scope.
5. `docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md` — current mapping
   from P1–P12, Profile Bootstrap, UI-1B, and Desktop to implementation and
   verification evidence.
6. `docs/reports/PRE_P13_PROFILE_CATALOG_STORAGE_UI_REVIEW_22.md` — latest
   Profile Catalog locking, storage containment, and Identity UI hardening.
7. `docs/reports/PRE_P13_PROFILE_POLICY_CONTROL_SESSION_REVIEW_23.md` — final
   implementation-closure handoff for live policy revocation, protected control
   Session authority, payment preflight, and Safety UI behavior; independent
   Grok acceptance passed for the open-source Runtime baseline.

The P10, P11, and P12 design documents define their complete target models.
Their final-acceptance reports record implementation coverage at acceptance
time; the pre-P13 reviews record later maintenance and adversarial corrections.

## Report families

| Family | Meaning |
| --- | --- |
| `phase1-*`, `phase2-*`, `p2-*`, `p3-*` | Historical P1–P3 transaction-gateway evidence. That product route is abandoned and retained only as opt-in legacy compatibility. |
| `p5-*`, `p6-*`, `P7_*`, `P8_*`, `P9_*` | Evolution from the first Agent browser loop to the managed Runtime, packaging, login/takeover, integration hardening, Visualizer, and Runtime safety. |
| `P10_*` | Web Object Model implementation and final acceptance. |
| `P11_*` | Agent Safety Contract implementation, security review, and final acceptance. |
| `P12_*` | Multi-Profile / Multi-Session implementation, authority rescoping, and Core acceptance. |
| `PROFILE_BOOTSTRAP_*` | Protected Cookie import, Profile clone, encrypted Bundle, and adversarial review. |
| `UI1B_*` | Same-page Session Monitor projection and HumanControlLease. This supersedes the retired duplicate-page AuthSurface. |
| `PRE_P13_*` | Cross-cutting closure reviews after P12. Each report is a completed review iteration; the overall closure Goal remains active until explicitly closed. |

Some early reports overlap or duplicate the same historical acceptance run. They
are kept for provenance and must not be counted as independent proof. Generated
`.release/` evidence is candidate-local and is intentionally not treated as a
durable source-of-truth document.

## Current scope boundary

P13 Durable Trace / Resume is deferred. The optional Desktop is a lightweight Runtime Manager and human monitoring/approval/takeover surface. It does not
plan tasks, decide actions, retain Agent memory, or turn WebFA into an Agent.
