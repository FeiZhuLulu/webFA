# WebFA Reports Index

The files in this directory are point-in-time engineering evidence. They do not
override the current code, automated tests, public documentation, or release
checklist, and an older passing report is not a release certificate for a new
artifact.

## Current document

Read `CURRENT_BASELINE.md`. It consolidates P10–P12 acceptance and Profile
Bootstrap into one baseline.

Public product contract, security boundary, and release gates still come first:

1. `README.md` or `README.en.md`
2. `docs/OPEN_SOURCE_READINESS.md` and `SECURITY.md`
3. `RELEASE_CHECKLIST.md`
4. `docs/browser-runtime-roadmap.md`
5. `docs/reports/CURRENT_BASELINE.md`

P10, P11, and P12 design documents remain the complete target models.

## Archived

P1–P3 transaction-gateway evidence and the former per-phase / per-iteration
reports were moved to the workspace archive:

```text
../备份/2026-08-22-reports-archive/
```

They remain provenance only.

## Current scope boundary

Human preview UI is not a product goal. Leftover Desktop / Monitor code does
not plan tasks, decide actions, retain Agent memory, or turn WebFA into an
Agent. Durable task resume is abandoned and is not a current phase.
