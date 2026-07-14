# Profile Bootstrap Clone Report

Status: implemented and accepted

Date: 2026-07-13

## 1. Scope

This phase implements protected cold cloning of one persistent BrowserProfile into a new persistent BrowserProfile.

The operation copies browser identity and website storage while deliberately creating a fresh WebFA authorization envelope.

Copied identity scope:

```text
Default Chromium website identity only
Cookies and Local State required by Chromium credential storage
localStorage
IndexedDB
Service Worker state
site permissions and durable website state
```

Explicitly excluded human-browser scope:

```text
History, Favicons, Top Sites, Shortcuts, and Visited Links
Bookmarks
Login Data and account password databases
Web Data, autofill, affiliation, and account-personal databases
current/last Sessions and open Tabs
Extensions and extension settings
non-Default Chromium subprofiles such as Profile 1
runtime, component, shader, GPU, download, and browser caches
selected transport/reporting state
```

Not inherited:

```text
AgentProfileGrant
bound_agent_ids
allowed_origins
Safety policy binding
Financial policy binding
active BrowserSession
Agent lease
HumanControlLease
Monitor Grant
P11 short-lived authority
SafetyReceipt history
```

The default Agent MCP surface remains exactly five tools. Profile clone is available only through the protected local control plane.

## 2. Cold Clone Model

Source Profile requirements:

- persistent;
- catalog state `ready`;
- no active BrowserSession or maintenance operation;
- exact Profile version match.

Target requirements:

- always a new generated Profile ID;
- persistent;
- new alias and display metadata;
- fresh user-owned/guarded defaults unless the local control payload explicitly selects other safe catalog metadata;
- bootstrap source forced to `cloned`.

Cloning into an existing Profile is not supported. This avoids overwriting an established internet identity and removes a large class of merge and rollback ambiguity.

## 3. Two-Phase Flow

```text
close source Session
  -> protected clone preview
  -> source ProfileMutationLease
  -> storage snapshot and fingerprint
  -> release preview lease
  -> redacted preview
  -> explicit target metadata and confirmation
  -> reacquire source ProfileMutationLease
  -> recompute source fingerprint
  -> acquire new target ProfileMutationLease
  -> copy into short target-local staging directory
  -> verify staged snapshot
  -> atomically replace target user-data directory
  -> create target Profile catalog record
  -> secret-free source/target events
  -> release both mutation leases
```

The preview token is bound to:

```text
control-token digest
source_profile_id
source_profile_version
storage fingerprint
expiry
```

## 4. Consistency Fingerprint

The storage snapshot fingerprints the accepted identity-transfer tree using:

- relative path;
- entry type;
- file size;
- nanosecond modification timestamp;
- SHA-256 of every file's contents.

Each file is stat-checked before and after hashing. A concurrent change during snapshot creation fails closed. Commit recomputes the complete content-bound source snapshot while holding the source mutation lease. Equal-size changes with restored timestamps are still detected and produce `profile_clone_source_changed`.

After copying, the staging tree is independently rescanned. File count, byte count, and fingerprint must match before target registration.

## 5. Filesystem Safety

The copy walker:

- never follows symbolic links;
- rejects directory junctions and unsupported filesystem entries;
- uses deterministic sorted traversal;
- copies regular files with metadata preservation;
- checks available disk space with an additional safety margin;
- requires an empty generated target storage directory;
- uses a target-local short staging path to remain compatible with Windows path limits.

The transfer walker implements an identity-focused boundary rather than copying an entire human browser. It excludes runtime artifacts, caches, browser-history databases, bookmarks, password/autofill databases, session/tab restoration data, extensions, and all non-Default Chromium subprofiles.

Durable website identity under the `Default` profile is retained. Managed Chromium is also launched with `--profile-directory=Default` and `--disable-extensions`, so one WebFA BrowserProfile remains one explicit internet identity rather than a container for several Chrome profiles or extension environments.

## 6. Atomic Catalog Boundary

Target storage is fully copied and verified before the target BrowserProfile is inserted into the catalog.

If target catalog creation fails, including alias conflict:

```text
target lock is released
unregistered target Profile root is deleted
preview remains usable for retry
no half-created catalog entry remains
```

If source storage changes, the preview is invalidated rather than retried against a different identity snapshot.

The source and target locks remain held through target catalog creation and secret-free runtime event recording.

## 7. Protected API

Control-only endpoints:

```text
POST /v1/profiles/{source_profile_ref}/bootstrap/clone/preview
POST /v1/profiles/{source_profile_ref}/bootstrap/clone/cancel
POST /v1/profiles/{source_profile_ref}/bootstrap/clone
```

Preview returns only:

- source safe alias and version;
- file count;
- total byte count;
- excluded runtime-entry count;
- expiry;
- opaque preview token.

It does not return filenames, paths, Cookie data, storage keys, or browser values.

## 8. Desktop Control UI

The Profile Bootstrap panel now supports:

- selecting a source persistent Profile;
- explicitly closing its active Session;
- generating a clone preview;
- entering a new alias and display name;
- confirming that Agent and policy bindings will not be inherited;
- cancelling the preview;
- creating the target Profile and refreshing the Profile catalog.

## 9. Real Chromium Validation

The real Chromium integration test:

1. creates a source Profile;
2. writes a persistent Cookie, localStorage value, and IndexedDB value;
3. closes the source Host;
4. previews and commits a Profile clone;
5. launches source and target Profiles concurrently;
6. verifies both initially contain the same identity state;
7. mutates the target Profile;
8. verifies the source Profile remains unchanged.

This proves website identity transfer and post-clone isolation. It does not claim to copy a person's browser history, bookmarks, saved-password vault, extension environment, or complete browser personalization.

## 10. Failure and Race Coverage

Tests cover:

- source Profile active during preview;
- source storage change after preview;
- wrong control token;
- target alias conflict;
- cleanup of unregistered target storage;
- retrying the same preview after a recoverable target conflict;
- runtime artifact exclusion;
- history, bookmarks, password/autofill data, sessions/tabs, extensions, and non-Default Chromium profile exclusion;
- content-hash detection of equal-size source changes with restored timestamps;
- empty and nested storage trees;
- Windows path-length-compatible staging;
- symbolic-link rejection when supported by the host OS;
- target policy non-inheritance;
- real Chromium storage clone and isolation.

## 11. Security Boundary

Clone data never enters:

- MCP requests or responses;
- Agent WebState or BrowserState;
- Monitor events;
- SafetyReceipt;
- local resource grants;
- control-plane preview payloads;
- Profile runtime event metadata.

Only safe counts, generated Profile IDs, and catalog aliases are returned.

## 12. Remaining Profile Bootstrap Work

Implemented:

```text
human login
Cookie import
Profile clone
```

WebFA Profile Bundle export/restore is also complete. It reuses ProfileMutationLease, the safe clone walker, redacted previews, and the non-Agent control boundary established here.

Bundle report:

```text
docs/reports/PROFILE_BOOTSTRAP_BUNDLE_REPORT.md
```

Post-Core Profile Bootstrap is complete.
