# Pre-P13 Storage Concurrency and Safety UI Review — Iteration 12

Date: 2026-07-18  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration closed a real shared-data-directory startup race and improved the
existing Safety Center without changing the product boundary. WebFA remains the
internet Runtime used by independent external Agents. The optional Desktop
remains a lightweight Runtime host, monitor, approval, and HumanControl surface;
it gained no model, planner, task loop, memory, or Agent orchestration.

## Storage defect and correction

A 12-process first-start stress run against one fresh `WEBFA_HOME` reproduced a
P12 migration race: only 7 processes completed, while 5 failed with either
`sqlite3.OperationalError: table browser_profiles already exists` or a unique
constraint failure on `storage_migrations.migration_id`.

`storage.db.init_db()` now serializes the complete additive initialization
sequence—schema creation, migration recording, and provider seeding—through one
thread lock plus a bounded cross-platform OS file lock inside the shared WebFA
data directory. The public migration note records that concurrency contract.

Two regressions protect the correction:

- 12 independent Python processes now initialize the same fresh data directory
  successfully, with exactly one P12 migration record and two provider seeds.
- A manually constructed pre-P12 database upgrades additively, preserves its
  existing connected GitHub provider row, creates the P12 catalog, and remains
  idempotent across a second initialization.

## Safety Center UI closure

The existing management surface was reorganized into semantic `section` / `h3`
groups for Step-up requests, Profile policy, financial policy, payment-tool
references, and safety receipts. Every dense policy control now has a visible
label in addition to its accessible name, limit fields use responsive grids,
and component-level inline styles were removed from this panel.

Visual review found that the compact drawer inherited a translucent sidebar
background, allowing the stopped-Runtime card and button to show through form
controls. The compact drawer now uses an opaque management background. This is
a presentation correction only; it adds no authority or behavior.

Production static Renderer evidence is stored locally under
`.release/ui-audit/safety-center-20260718`. DOM evidence records all five
sections, 20 visible field labels, `H3` heading levels, and no document or panel
horizontal overflow at 1440x960 and 390x844. Upper and lower captures were
visually inspected:

- `safety-center-desktop.png` — SHA-256
  `22F7C2C6067DB303D6549C1B99D0BACD3516705DB1EB61D1DBC258C6C96B7DDA`
- `safety-center-desktop-lower.png` — SHA-256
  `8E906E5F80C4AC62520D1D9428B94F5CADF3A679537CEEC328D4A5D307F4079E`
- `safety-center-compact.png` — SHA-256
  `3A4BE31A4121D4C4916D21E8C353E97B7AF48F8F9C9FB9FAAE9B0A6313E46CD1`
- `safety-center-compact-lower.png` — SHA-256
  `E7525B2AA065C7B1E93CCC00EE147E9CA38A2412FDE3210E964743EB2D534DF7`

The static capture intentionally had no protected Runtime control token, so its
controls were disabled. It is visual/layout evidence, not a claim of functional
form submission or complete assistive-technology acceptance. Those installed
management-flow gates remain open in `RELEASE_CHECKLIST.md`.

## Verification

- The initial full Python run exposed one stale wording contract after 611
  passes and 1 skip; the contract now correctly expects “外部 Agent”.
- Final Python suite: 615 passed, 1 skipped, 2 third-party deprecation warnings.
- Electron process/release suite: 26 passed, 0 failed.
- Renderer production build passed for `/`, `/_not-found`, `/icon.png`, and
  `/monitor`; Renderer and Electron TypeScript checks passed.
- Focused storage/Profile/Supervisor concurrency set: 18 passed.
- Focused Renderer/storage/Desktop contracts: 19 passed.
- `git diff --check` passed; only the repository's existing Windows line-ending
  notices were emitted.

## Remaining scope

The overall pre-P13 goal remains active for maintenance and adversarial review.
P13 Durable Trace / Resume remains paused. Desktop work remains limited to
defects, accessibility, clarity, and visual polish on the lightweight Runtime
Manager; deeper Desktop application or Agent functionality is out of scope.
