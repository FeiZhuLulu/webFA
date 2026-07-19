# Pre-P13 Profile Catalog, Storage, and Identity UI Review — Iteration 22

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop
expansion remain deferred

## Outcome

This iteration reviewed the destructive and offline lifecycle boundary around a
persistent internet identity: Catalog archive/restore, active Session and
maintenance exclusion, Profile storage containment, and the lightweight
Desktop identity-maintenance presentation.

One reproducible Catalog race and one filesystem-containment weakness were
fixed. The Desktop change is deliberately limited to clearer labels, truthful
Bundle copy, and stronger visual audit coverage; it adds no Agent behavior or
new management responsibility.

## Defects reproduced and corrected

### 1. Soft restore changed Catalog state without the required mutation lease

The frozen P12 design requires restore and other offline Profile mutations to
share the OS-backed `ProfileMutationLease`. Archive acquired the lease, but
`POST /v1/profiles/{profile_ref}/restore` changed an archived Profile to `ready`
even while another maintenance operation held the Profile lock.

The failure was reproduced through the protected control API: the endpoint
returned 200 and incremented the version while a competing Bundle-restore
mutation lease remained active. Restore now resolves the canonical Profile,
acquires a `profile_restore` mutation lease, changes Catalog state only while the
lease is held, returns structured `profile_busy` on contention, and leaves state
and version unchanged. Archive contention, default-Profile rejection, and the
active-Session prohibition also have explicit regression coverage.

### 2. Managed Profile directory roots did not reject link redirection

Profile IDs already rejected path separators, but the managed Profile root and
its direct Chromium user-data, downloads, and maintenance directories could be
pre-created as symbolic links or Windows directory junctions. That allowed
filesystem placement to redirect otherwise opaque Profile storage away from the
managed root.

`ProfileStorageManager` now rejects link/junction substitution before and after
directory creation, including `create=False` callers, and rejects colon-based
drive/alternate-stream syntax in Profile IDs. Unit coverage exercises traversal,
drive syntax, simulated root/child link classification, and the existing clone
tree link rejection. A real Windows Junction was also created beneath an owned
`.tmp` audit directory: the manager returned `profile_storage_unsafe`, the
outside sentinel remained intact, and the audit directory was removed afterward.

## Identity UI review

The Identity workspace exposed its Profile, Cookie, Clone, and encrypted Bundle
inputs with accessible names, but most labels disappeared once a placeholder
was replaced by a value. The fields now use the same persistent visible-label
system as the Safety workspace. This improves scanning without adding another
Desktop workflow.

The Bundle description no longer says it contains a complete browser identity.
It now describes encrypted, filtered website identity state and explicitly
excludes passwords, autofill, history, bookmarks, tabs, and extensions.

The production source UI audit now captures the Identity workspace at 1440 ×
960 and inside the 390 × 844 modal drawer in addition to its previous eight
states. Both Identity captures were visually inspected at original resolution.
They retain one bounded scroll region, visible field hierarchy, readable disabled
states, and the established warm-neutral visual system. Automated evidence for
both states reports no horizontal overflow, escaped controls, unnamed visible
buttons, or unlabeled visible fields; the mobile drawer remains opaque and modal
with two inert background regions.

## Verification

- Full Python suite: 669 passed, 2 skipped.
- Focused Profile Catalog/storage/Renderer contracts: 34 passed, 1 skipped.
- Electron lifecycle and release suite: 26 passed.
- Renderer and Electron TypeScript: passed.
- Next production Renderer build: passed.
- Source UI audit: passed, 10 captures.
- Original-resolution visual inspection: Identity desktop and mobile passed.
- Real Windows directory Junction containment check: passed; outside sentinel
  preserved and generated audit state cleaned.
- `git diff --check`: passed.

The two full-suite skips remain environment-specific: POSIX permission bits do
not represent Windows ACLs, and ordinary symbolic-link creation is unavailable
in the current test environment. The separate real Junction check provides
Windows link-redirection evidence for this iteration.

## Scope boundary

P13 Durable Trace / Resume remains deferred. The Desktop remains a lightweight
Runtime Manager and human control surface; no model, planner, memory, task loop,
or Agent orchestration was introduced.

