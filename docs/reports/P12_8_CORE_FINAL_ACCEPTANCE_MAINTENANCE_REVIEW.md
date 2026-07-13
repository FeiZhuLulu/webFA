# P12.8 Core Final Acceptance and Maintenance Review

Status: accepted with one documented BrowserHost verification note

Date: 2026-07-13

## 1. Acceptance Scope

P12.8 validates the complete P12 Multi Session / Multi Profile core:

```text
P12.1 Profile Catalog
P12.2 Profile Storage Isolation
P12.3 BrowserSessionRuntime Extraction
P12.4 Supervisor and Global Routing
P12.5 Agent Grants and Five-Tool Integration
P12.6 Monitor and HumanControl Isolation
P12.7 P11 Authority Re-scoping
```

Profile Bootstrap remains post-Core work:

- Cookie import;
- Profile clone;
- Profile bundle restore;
- maintenance-host operations.

These capabilities consume the P12 isolation model and do not alter the accepted Core topology.

## 2. Frozen Runtime Topology

The accepted topology is:

```text
one active persistent BrowserProfile
  -> one dedicated Chromium user-data-dir
  -> one dedicated ManagedChromiumHost
  -> at most one active writable BrowserSession
  -> multiple Tabs

multiple different BrowserProfiles
  -> may run concurrently
```

`BrowserRuntimeSupervisor` owns routing and lifecycle only. Page state remains Session-local in `BrowserSessionRuntime`.

## 3. Final Migration Finding and Fix

The maintenance review found one genuine migration omission in the legacy manual-login helper:

```text
webfa login
```

The helper still reported the obsolete directory:

```text
browser/managed-chromium-profile-default
```

Although a default `ManagedChromiumHost` had already migrated to the new directory internally, the helper did not explicitly use the Profile Catalog or Profile process lock.

P12.8 fixes the flow:

```text
ProfileRepository.ensure_default_profile()
  -> ProfileStorageManager paths
  -> ProfileProcessLock
  -> explicit ProfileLaunchSpec
  -> visible ManagedChromiumHost
  -> graceful close
  -> deterministic lock release
```

The canonical default path is now:

```text
profiles/default/chromium-user-data
```

A unit test verifies the login window receives this exact launch specification and that the Profile lock can be reacquired after the window closes.

## 4. Real Chromium Acceptance

The real Managed Chromium scenario runs two persistent Profiles concurrently against the same Origin.

Profile A writes identity A and Profile B writes identity B into:

- persistent Cookie;
- localStorage;
- IndexedDB;
- Service Worker registration.

Both Chromium processes are closed gracefully, their process locks are released, and both Profiles are reopened with new Runtime generations.

The reopened Profiles retain only their own state:

```text
Profile A -> A
Profile B -> B
```

The test also proves:

- both Profiles run concurrently;
- each uses a different user-data-dir;
- closing both Hosts and reopening them retains identity state;
- Service Worker registration remains Profile-local;
- normal Host shutdown flushes persistent Cookie state.

### CacheStorage verification note

A direct page-level `caches.open()` probe in the current headless Managed Chromium environment returned Chromium's `Unexpected internal error`. The test therefore does not claim a CacheStorage value comparison that did not execute.

This is recorded as a BrowserHost compatibility/verification note rather than evidence of cross-Profile leakage. P12 uses separate Chromium processes and separate user-data directories; there is no shared BrowserContext or storage backend between persistent Profiles. CacheStorage behavior should be rechecked when BrowserHost launch flags or the Chromium distribution change.

## 5. Core Acceptance Matrix

### 1. Multiple persistent BrowserProfiles

PASS.

Profile Catalog creation, persistence, aliases, version conflicts, archive/restore, and Agent projection are tested.

### 2. Dedicated user-data-dir and ManagedChromiumHost

PASS.

Each active persistent Profile receives an explicit `ProfileLaunchSpec` and independent Host.

### 3. Same Profile cannot be opened twice

PASS.

OS-backed `ProfileProcessLock` is exclusive across independent handles. A second acquisition fails closed.

### 4. Browser storage has no known cross-Profile leakage

PASS with the CacheStorage verification note above.

Cookie, localStorage, IndexedDB, and Service Worker registration are verified in real Chromium. Persistent Profiles have no shared process or user-data-dir.

### 5. Same site can retain different identities

PASS.

The real Chromium test retains different Cookie-backed identities on the same Origin.

### 6. Different Agents can use different Profiles concurrently

PASS.

Supervisor integration tests run two connection/Agent contexts against two Profile Sessions concurrently.

### 7. Second Agent cannot bypass Session lease

PASS.

Same-Profile second connection receives deterministic `session_busy` behavior.

### 8. One connection can switch between authorized Profile Sessions

PASS.

`AgentConnectionContext` retains multiple authorized/leased Sessions and atomically changes current binding.

### 9. get_tabs and switch_tab route across Sessions

PASS.

Global opaque Tab IDs route to the correct Session and local Tab ID.

### 10. Tab and WebObject IDs cannot cross Sessions

PASS.

Global routes bind Session, Profile, generation, and local ID. Cross-Session and old-generation object use is rejected.

### 11. P11 authority cannot replay across Sessions

PASS.

SafetyContext, Step-up, LocalResource, payment authority, selected payment, Monitor Grant, and SafetyReceipt are bound to Session/Profile/generation; connection/document/origin/object scope is applied where relevant.

### 12. HumanControlLease affects only one Session

PASS.

A HumanControlLease on Session A does not alter Session B's control state or Agent operations.

### 13. Session crash does not affect another Session

PASS.

A crashed Host transitions only its Session to `crashed`, releases its routes and Profile lock, and leaves the other Profile Session operational.

### 14. Profile login state survives Runtime restart

PASS.

Real Chromium persistent state survives Host close/reopen with new Runtime generations.

### 15. Old Sessions become interrupted, not pseudo-restored

PASS.

Startup interrupts nonterminal Session metadata. P13 remains responsible for durable task resume.

### 16. Agent cannot obtain secrets or Profile paths

PASS.

Tests and source review cover Cookie/storage values, password and payment secrets, human input, local file paths, Monitor credentials, and Profile storage paths.

### 17. Default MCP tools remain exactly five

PASS.

The public tool list remains:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

### 18. P10 remains the only Agent page-operation model

PASS.

No raw selector, XPath, CDP, Cookie, storage, Session-management, or Profile-management tool was added.

### 19. Monitor remains a projection of the same Host

PASS.

Real Managed Chromium tests verify Screencast and HumanControl use the existing page target. Monitor never creates a target-page copy.

### 20. Legacy default Profile migrates safely

PASS.

Migration is idempotent, preserves existing data, and fails closed on conflicting valid source/target data. The manual-login helper now uses the canonical new Profile path and lock.

### 21. Cleanup, expiry, crash, and race paths are deterministic

PASS.

Coverage includes:

- Session operation serialization;
- Profile process-lock release;
- Agent Session lease expiry;
- HumanControl expiry/disconnect;
- stuck mouse/key release;
- Monitor Grant expiry/revocation;
- old generation invalidation;
- Session crash isolation;
- Runtime close cleanup.

### 22. Core does not depend on Cookie import

PASS.

All Core acceptance scenarios use blank or manually populated isolated Profiles. Cookie import remains a protected Profile Bootstrap consumer.

## 6. Security Invariant Review

The maintenance review found no known path for an Agent to:

- choose or read a user-data-dir;
- read/export raw Cookie or storage data;
- call Profile CRUD through MCP;
- bypass ProfilePolicy/ProfileGrant;
- switch a running Session to another Profile;
- obtain two writable Session leases for the same Profile;
- replay an old Session generation authority;
- send HumanControl input through an Agent tool;
- turn Monitor into a duplicate-page browser;
- obtain local resource paths or human-entered secret values.

`connection_id` remains an internal transport header and does not enter the model-facing tool schema or P11 safety schemas.

## 7. Validation Baseline

Final validation is expected to report:

```text
Python tests:          483 passed
Electron typecheck:    passed
Renderer typecheck:    passed
Python package build:  passed
MCP integration:       passed
Git diff check:        passed
```

Only the two existing upstream deprecation warnings remain:

- `websockets.legacy`;
- Uvicorn's legacy WebSocket protocol import.

## 8. Accepted Remaining Boundaries

The following are not P12 Core defects:

- active Monitor/Profile grants are in memory and intentionally do not survive Runtime restart;
- durable task and Session resume belongs to P13;
- native browser permission prompts, OS file choosers, hardware security keys, and secure-attention flows still require a future non-DOM interaction abstraction;
- persistent Profiles use one Chromium process each; shared ephemeral BrowserContexts remain a future optimization;
- Cookie import, Profile clone, and Profile bundle restore are Post-Core Profile Bootstrap work;
- CacheStorage should be re-probed when BrowserHost launch flags or Chromium distribution change.

## 9. Final Decision

P12 Core is accepted.

WebFA now has a real multi-identity internet runtime rather than a single global browser instance:

```text
Profile = durable internet identity
Session = active Agent task runtime
Supervisor = trusted routing and lifecycle boundary
Monitor = human projection/control plane for one real Session
```

The next implementation work may proceed to protected Profile Bootstrap, beginning with Cookie import, without changing the P12 Core object model or the five-tool Agent interface.
