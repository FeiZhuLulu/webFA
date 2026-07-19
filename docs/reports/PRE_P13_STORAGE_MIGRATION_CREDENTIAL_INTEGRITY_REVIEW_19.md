# Pre-P13 Storage Migration and Credential Integrity Review — Iteration 19

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration adversarially reviewed SQLite initialization, P12 migration
finalization, legacy Provider credential files, and the database/file boundary.
It fixed reproduced integrity and lifecycle defects without changing the five
Agent tools or adding any Desktop responsibility. Desktop remains an optional
lightweight Runtime Manager; the corrected code is owned by the Runtime storage
and protected human-control layers.

## Reproduced defects

The initial isolated reproduction under `.release/storage-repro/iteration-19`
proved all of the following against the pre-fix source:

### SQLite foreign keys were metadata only

`PRAGMA foreign_keys` returned `0`, and a `browser_sessions` row referencing a
nonexistent Profile was accepted. SQLAlchemy model declarations therefore did
not enforce the P12 Profile/Session ownership contract in SQLite.

### Credential references could escape their root

`CredentialStore.put("../escaped", ...)` wrote
`../escaped/default.json` outside the configured credentials directory. Read
operations also created Provider directories as a side effect, and writes
overwrote the final JSON path directly rather than atomically replacing it.

### A failed seed could leave a false migration milestone

The P12 migration record and required Provider placeholder rows committed in
separate transactions. A forced seed failure left
`p12_001_profile_catalog` recorded while no Provider rows existed.

### Provider routes queried the wrong identity

`ProviderConnection.id` is a generated record identifier, while `provider` is
the unique natural key. The legacy GitHub routes used
`session.get(ProviderConnection, "github")`, so they failed to find the seeded
row. Connect could then attempt a second `provider="github"` row and violate the
unique constraint; status could incorrectly report disconnected.

### Credential files and Provider metadata could diverge

Connect replaced the credential before testing and committing metadata, with no
restore path if the transaction failed. Disconnect deleted the credential
before the metadata commit, also without restore. A partial failure could leave
an orphan token or a database row claiming a missing credential.

## Runtime storage corrections

### Database initialization and migration integrity

- Engine construction is now double-checked under a process thread lock, so
  concurrent first callers receive one Engine and session factory.
- Every SQLite connection enables `foreign_keys=ON` and an explicit bounded
  busy timeout.
- The migration milestone and required Provider seed rows now commit in one
  transaction after additive schema creation.
- The existing cross-process storage initialization lock still serializes the
  complete first-start/upgrade sequence.
- The pre-P12 preservation path remains additive; no destructive or implicit
  column rewrite was introduced.

Enabling real foreign keys exposed a formerly hidden ordering defect in the
legacy transaction flow: Workspace and Plan were added in the same ORM unit as
AuditEvents containing scalar foreign-key IDs, but no AuditEvent relationships
gave SQLAlchemy a parent-before-child dependency. Workspace and Plan parents are
now explicitly flushed before their audit rows. GitHub workspace import applies
the same rule before snapshots and its completion audit. The complete
plan→preview→approve→execute flow now finishes with an empty
`PRAGMA foreign_key_check` result.

### Credential-file boundary

Credential Provider and connection segments now use a bounded identifier
grammar. Ambiguous refs, traversal, extra separators, and symbolic-link escape
are rejected. Reads and existence checks no longer create Provider directories.

Writes now use a private temporary file in the destination directory, flush and
fsync it, atomically replace the destination, apply private POSIX permissions,
and fsync the directory. Failed replacement preserves the previous complete
token and removes the temporary file. Credential JSON identity and token shape
are validated on read; token input is bounded to 16 KiB at both schema and
storage layers.

This remains a legacy plaintext local file store, not a hardware Vault or an
at-rest encryption claim. POSIX applies `0700` directories and `0600` files;
Windows inherits the local user-data ACL. Documentation now explicitly warns
against shared `WEBFA_HOME` directories and against assuming protection after
the local OS account is compromised.

### Provider lifecycle coherence

GitHub connection lookup now queries the unique `provider` column. Connect,
test, status, and disconnect are serialized by a Runtime process lock. Connect
captures the previous token and restores it (or deletes the new token) if
metadata commit fails. Disconnect similarly restores a removed token when its
metadata transaction fails. Rollback errors are bounded and never include raw
credential material.

Successful connect/status/disconnect coverage proves there remains exactly one
GitHub Provider row, response bodies exclude the submitted token, audits contain
only bounded status metadata, and successful disconnect removes the credential.

## Installed-wheel verification

A fresh `0.2.0` sdist and wheel were built under
`.release/python-dist/iteration-19-20260719`. The wheel was installed into the
source-isolated `.release/storage-audit/iteration-19-venv`; its imported Runtime
module resolved from that environment's `site-packages`.

The installed package then completed:

- migration initialization with exactly `p12_001_profile_catalog`;
- `PRAGMA foreign_keys = 1` and an empty `foreign_key_check`;
- rejection of an orphan BrowserSession;
- a full legacy mock plan→preview→human approve→execute flow ending `verified`;
- protected GitHub connect/status/disconnect with one Provider row and no token
  response leak;
- credential deletion and traversal rejection; and
- the unchanged exact default five-tool MCP list.

## Regression

- Python: 650 passed, 2 skipped; two third-party websocket deprecation warnings.
- New storage/credential/Provider/full-flow focus: 16 passed, 1 skipped on the
  Windows host; the skip is the POSIX permission-bit assertion.
- Previously failing transaction/approval/execution set after FK activation:
  28 passed.
- 12-process concurrent first-start initialization: covered by the full suite.
- Python `0.2.0` sdist/wheel build: passed.
- Installed-wheel storage/lifecycle audit: passed.
- Electron process/release suite: 26 passed.
- Electron and Renderer TypeScript checks: passed.
- Renderer production build: passed for `/`, `/_not-found`, `/icon.png`, and
  `/monitor`.
- `compileall` and `git diff --check`: passed apart from repository-wide Windows
  line-ending notices.

No Renderer or Electron behavior changed, so iteration 17 remains the accepted
visual evidence. This iteration rebuilt the Renderer only as a cross-layer
integration gate and did not make Desktop heavier.

## Remaining boundary

Provider PAT storage is historical, local, plaintext, and absent from the
default Agent MCP surface. Replacing it with platform keychains would be a
separate product/security design decision rather than a hidden closure change.
Runtime/MCP remains a loopback/local contract. P13 Durable Trace / Resume and
Desktop expansion remain deferred; the overall closure goal remains active.
