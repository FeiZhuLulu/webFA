# P12.1-P12.3 Profile and Session Foundation Report

Status: complete

Date: 2026-07-13

Scope:

```text
P12.1 Schema and Profile Catalog
P12.2 Profile Storage Isolation
P12.3 Session Runtime Extraction
```

P12.4 global multi-Profile routing is not part of this report.

## 1. Result

WebFA no longer treats the default browser identity as only an in-memory policy entry and a hard-coded Chromium directory. The Runtime now has a persistent BrowserProfile catalog, explicit Profile storage specifications, an OS-backed Profile process lock, persistent BrowserSession metadata, a Session-scoped Runtime implementation, and an application-level Supervisor foundation.

The production REST path creates a `BrowserRuntimeSupervisor`. The old `BrowserRuntime` name remains as a compatibility subclass for single-session tests and direct integrations, but the page-operating implementation is now `BrowserSessionRuntime`.

## 2. P12.1 Schema and Profile Catalog

Added:

- `schemas.profile.BrowserProfileCreate`;
- `BrowserProfileUpdate` with optimistic `expected_version`;
- internal/local `BrowserProfile`;
- secret-reduced `BrowserProfileAgentView`;
- `BrowserSessionMetadata` and lifecycle types;
- persistent Profile and Session SQLAlchemy models;
- `ProfileRepository` and `BrowserSessionRepository`;
- protected local Profile CRUD API under `/v1/profiles`;
- storage migration ledger entry `p12_001_profile_catalog`.

SQLite tables:

```text
browser_profiles
browser_profile_agent_bindings
browser_sessions
browser_profile_runtime_events
storage_migrations
```

Profile catalog behavior:

- opaque stable Profile ids;
- unique normalized `agent_alias`;
- local-only `display_name` and `storage_ref`;
- persistent Agent bindings and Origin policy;
- persistent P11 owner, trust mode, safety policy and financial policy metadata;
- optimistic version conflict detection;
- soft archive and restore;
- default Profile cannot be archived;
- active Profile sessions prevent archival.

`ProfilePolicyStore` can now project through `ProfileRepository`, so P11 Profile policy does not diverge from the persistent catalog.

## 3. P12.2 Profile Storage Isolation

Added:

```text
ProfileStorageManager
ProfileStoragePaths
ProfileLaunchSpec
ProfileProcessLock
```

Persistent Profile layout:

```text
profiles/<profile_id>/
  chromium-user-data/
  downloads/
  maintenance/
  profile.lock
```

`ManagedChromiumHost` now accepts an explicit `ProfileLaunchSpec`. Production Session creation passes the Profile-specific user-data-dir into the Host instead of allowing the Host to derive a global directory.

The lock implementation uses the operating system's non-blocking file lock:

- Windows: `msvcrt.locking`;
- POSIX: `fcntl.flock`.

The OS lock is authoritative. Lock metadata is informational and contains only bounded identifiers and PID; stale text is never treated as proof that a live lock can be removed.

Legacy migration moves:

```text
browser/managed-chromium-profile-default
```

to:

```text
profiles/default/chromium-user-data
```

The migration fails closed if both locations contain data.

### Chromium shutdown correction

Real persistence validation found that force-terminating Chromium could leave the Cookie database unflushed even though localStorage and IndexedDB had persisted. `ManagedChromiumHost.close()` now requests CDP `Browser.close` first, waits for normal process exit, and only then falls back to terminate and kill.

## 4. Real Chromium isolation validation

The P12 integration test launches two Managed Chromium Hosts concurrently with two distinct ProfileLaunchSpecs against the same Origin.

Profile A writes identity `A`; Profile B writes identity `B` into:

- persistent Cookie;
- localStorage;
- IndexedDB.

Both Hosts are closed, their process locks are released, and both Profiles are started again. The test confirms:

- A retains only A;
- B retains only B;
- Cookie, localStorage and IndexedDB do not cross Profile boundaries;
- both persistent Profile directories can run concurrently;
- graceful shutdown preserves browser state.

## 5. P12.3 Session Runtime Extraction

The former single-session implementation was renamed to:

```text
BrowserSessionRuntime
```

Each instance now has explicit:

```text
session_id
profile_id
runtime_generation
job queue
worker thread
operation lock
ObjectRegistry
SessionEventBus
P11 short-lived state
HumanControl state
visual/document binding
```

`_BrowserWorker` is now `SessionWorker` and constructs `BrowserSession` with explicit Session, Profile and generation identifiers.

The compatibility class:

```text
BrowserRuntime(BrowserSessionRuntime)
```

preserves existing direct single-session tests without creating a second implementation.

## 6. Supervisor foundation

Added `BrowserRuntimeSupervisor` as the production application facade.

P12.3 responsibilities implemented:

- ensure or resolve the default persistent Profile;
- acquire ProfileProcessLock before migration or Session creation;
- safely mark stale nonterminal Sessions for that Profile as interrupted only after obtaining the Profile lock;
- create opaque Session id and runtime generation;
- build explicit ProfileLaunchSpec;
- create and persist BrowserSession metadata;
- construct BrowserSessionRuntime;
- expose existing single-session methods through delegation;
- mark Session starting, running, closed or crashed;
- release Profile lock on deterministic close or Host crash;
- preserve health and Visualizer status compatibility.

P12.4 will replace the one-current-Session foundation with multiple active SessionRuntime instances and global routing.

## 7. Crash behavior

A Supervisor-managed Session does not silently restart a crashed Host inside the same Session generation.

On detected Host exit:

```text
BrowserSession -> crashed
health -> failed
close_reason -> bounded host error
ProfileProcessLock -> released
```

A new Supervisor/Session generation can then acquire the same Profile. Direct compatibility `BrowserRuntime` instances without a SessionRepository retain the historical host-restart behavior for the migration period.

## 8. Monitor compatibility

Internal Sessions now use opaque ids. During P12.3 the local Monitor control API still accepts the legacy request alias:

```text
session_id = "default"
```

It resolves that alias to the current Supervisor Session and issues the grant for the real opaque Session id. Frame metadata and Runtime state use the real Session id.

This compatibility alias is local-control-plane-only and does not restore a global default Session model.

## 9. Public Agent boundary

No MCP tool was added.

The default Agent surface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

P12.1-P12.3 do not expose:

- Profile CRUD to Agents;
- Profile paths;
- Cookie or storage values;
- Cookie import;
- Session management tools;
- raw Host or CDP operations.

## 10. Validation

```text
Python tests:          465 passed
Electron typecheck:    passed
Renderer typecheck:    passed
Python package build:  passed
Git diff --check:      passed
```

The Python suite includes:

- Profile catalog persistence and optimistic concurrency;
- Agent projection redaction;
- persistent P11 Profile policy;
- Session lifecycle and interruption;
- OS Profile lock exclusivity;
- default Profile directory migration;
- Supervisor Session/generation creation;
- Host crash terminal state and lock release;
- protected Profile CRUD API;
- real two-Profile Chromium storage isolation and restart persistence;
- all existing P10, P11 and UI-1B regression tests.

Two existing upstream deprecation warnings remain:

- `websockets.legacy`;
- Uvicorn legacy WebSocket protocol import.

## 11. Remaining P12 work

P12.1-P12.3 establish the correct storage and Session foundation, but do not yet provide multi-Profile Agent routing.

Next phase:

```text
P12.4 Supervisor and Global Routing
```

It must add:

- multiple active ProfileRuntime/BrowserSessionRuntime entries;
- SessionManager;
- AgentConnectionRegistry;
- GlobalRouteRegistry;
- globally routed Tab and WebObject identities;
- concurrent execution across different Profiles;
- per-Session fault isolation at the Supervisor routing layer.

P12.5 then adds connection-level Profile grants, AgentSessionLease, optional `profile_ref`, and five-tool multi-Session behavior.
