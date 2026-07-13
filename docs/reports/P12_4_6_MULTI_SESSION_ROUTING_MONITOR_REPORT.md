# P12.4-P12.6 Multi-Session Routing and Monitor Isolation Report

Status: implemented and accepted

Date: 2026-07-13

Covered phases:

```text
P12.4 Supervisor and Global Routing
P12.5 Agent Grant and Five-Tool Integration
P12.6 Monitor and Human Control Isolation
```

This stage converts the P12.1-P12.3 single-current-Session foundation into an actual concurrent multi-Profile Runtime while preserving the frozen WebFA product boundary: Agents still operate the web through exactly five browser tools, Browser Profiles remain protected identity containers, and the Monitor remains a projection of the same BrowserHost page.

---

## 1. Delivered Architecture

The active Runtime topology is now:

```text
Agent connection A
  -> AgentConnectionContext A
  -> Profile grant / Session lease
  -> current Session A
  -> BrowserSessionRuntime A
  -> dedicated Profile A Host

Agent connection B
  -> AgentConnectionContext B
  -> Profile grant / Session lease
  -> current Session B
  -> BrowserSessionRuntime B
  -> dedicated Profile B Host

BrowserRuntimeSupervisor
  -> SessionManager
  -> AgentConnectionRegistry
  -> AgentProfileGrantManager
  -> AgentSessionLeaseManager
  -> GlobalRouteRegistry
  -> ProfileRepository / BrowserSessionRepository
  -> ProfileStorageManager
```

Different Profiles may run concurrently. The same Profile still has at most one active writable Session.

---

## 2. P12.4 Supervisor and Global Routing

### 2.1 SessionManager

Added `browser/session_manager.py` with:

- `ActiveBrowserSession`;
- active Session lookup by `session_id`;
- active Session lookup by `profile_id`;
- one-active-Session-per-Profile enforcement;
- deterministic add/remove/default-Session behavior;
- separation of live Runtime state from durable `BrowserSessionRepository` metadata.

`BrowserRuntimeSupervisor` now owns multiple `BrowserSessionRuntime` instances through this manager rather than storing a single Runtime.

### 2.2 Concurrent Profile sessions

For each active Profile, Supervisor creates and owns:

```text
ProfileProcessLock
ProfileLaunchSpec
BrowserSession metadata
BrowserSessionRuntime
runtime_generation
```

Two different Profiles can run two independent Hosts concurrently. A Host crash or Session closure removes only that Session, releases only its Profile lock, invalidates only its routes and leases, and leaves other Sessions running.

### 2.3 GlobalRouteRegistry

Added a Runtime-private route registry for globally opaque identifiers.

Local Host identifiers such as:

```text
tab_1
obj_1
```

are projected to Agent-visible identifiers such as:

```text
tabr_<opaque digest>
objr_<opaque digest>
```

Each route binds:

```text
session_id
profile_id
runtime_generation
local_id
```

The registry projects and localizes:

- Tab IDs;
- WebObject IDs;
- outline and region references;
- object relations;
- ChangeSet additions, updates, removals and invalidations;
- takeover targets;
- object and query observe requests;
- semantic operation targets.

A WebObject from Session A cannot be sent to Session B. A route from an old runtime generation cannot address a replacement Session.

### 2.4 Cross-Session tab switching

`webfa.get_tabs` now returns authorized Tabs across the connection's leased Sessions. Each Tab includes:

```text
id
session_id
profile_id
profile_ref
runtime_generation
url
title
active
```

`webfa.switch_tab(tab_id)` resolves the global Tab route. Switching to a Tab in another Session atomically changes the Agent connection's current Session binding before operating the local Host Tab.

---

## 3. P12.5 Agent Grant and Five-Tool Integration

### 3.1 Connection identity

Each MCP Runtime client now creates a high-entropy connection identifier and sends:

```text
X-WebFA-Agent-Id
X-WebFA-Connection-Id
X-WebFA-MCP-Tool
```

The Agent model does not supply the connection ID. A connection ID cannot change Agent identity during its lifetime.

Legacy direct HTTP calls without the new header receive a deterministic compatibility connection derived from the Agent ID.

### 3.2 AgentConnectionContext

Each connection tracks:

- Agent identity;
- current Session and Profile;
- authorized Profiles;
- leased Sessions;
- binding revision;
- TTL and activity timestamps;
- a connection-level operation lock.

The connection operation lock serializes `open_url`, `switch_tab`, `observe` and `act` changes to the implicit current-Session pointer. Different connections and different Profile Sessions remain concurrent.

### 3.3 AgentProfileGrant

Profile selection is no longer equivalent to raw directory selection.

A Profile grant checks:

- Profile catalog state;
- persistent Profile policy;
- `bound_agent_ids`;
- Agent and connection identity;
- grant expiry.

The Agent sees `profile_ref`, not a storage path or Chromium Profile directory.

### 3.4 AgentSessionLease

Write authority is exclusive per Session and is bound to:

```text
agent_id
connection_id
session_id
profile_id
runtime_generation
expiry
```

A second Agent connection cannot write the same active Profile Session. Different Profile Sessions can be controlled concurrently.

The local Visualizer compatibility path does not acquire an Agent write lease. This prevents local policy inspection or configuration from accidentally blocking the actual Agent.

### 3.5 Five-tool surface

The default MCP tools remain exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Only `webfa.open_url` gains one optional Agent-native argument:

```text
profile_ref
```

No Profile CRUD, Session management, Cookie, Storage, selector, CDP or browser primitive tool was added.

`open_url(profile_ref=...)` selects or creates the authorized Profile Session and makes it current for that connection. `observe` and `act` continue to operate on the connection's current Session without requiring repetitive `session_id` arguments.

---

## 4. P12.6 Monitor and Human Control Isolation

### 4.1 Session selection control API

Added local protected endpoint:

```text
GET /v1/visualizer/sessions
```

It returns active Session summaries for the Control Center. Local-only display metadata remains outside the Agent protocol.

Monitor grants can now target any exact active Session instead of only the previous global active Runtime.

### 4.2 Monitor grant generation binding

Monitor capability state now includes:

```text
session_id
profile_id
runtime_generation
permissions
expiry
```

`MonitorGatewayRouter` resolves and validates this binding before a WebSocket is attached to a `BrowserSessionRuntime`.

A grant for an old generation fails closed after the Session is replaced, even if the same Profile is active again.

### 4.3 Session-specific WebSocket routing

After one-time Token consumption, the Monitor WebSocket obtains the exact `BrowserSessionRuntime` for the grant. All subsequent operations are performed on that Runtime only:

- SessionEventBus subscription;
- state snapshots;
- visual stream;
- HumanControlLease;
- human input;
- disconnect cleanup.

The WebSocket does not depend on the Supervisor's default/current Session after authentication.

### 4.4 VisualStreamHub

The Session visual provider is now an explicit `VisualStreamHub`.

A Session still starts at most one backend `Page.startScreencast`, but the hub fans its Host frames out to multiple independently queued consumers:

```text
one BrowserHost screencast
  -> Monitor A
  -> Monitor B
  -> Control Center preview
```

Stopping one consumer does not stop the backend while other consumers remain. Slow or failed consumers do not block the Host or other consumers. Conflicting Host-level stream configurations fail deterministically.

`BoundVisualSurfaceProvider` remains as a compatibility subclass, not a second implementation.

### 4.5 HumanControl isolation

HumanControlLease remains owned by each `BrowserSessionRuntime`.

Consequently:

- Human takeover in Session A pauses Agent writes only in Session A;
- Session B remains observable and operable;
- human input is dispatched only to the Host bound to the Monitor grant;
- Monitor disconnect cleanup releases only the corresponding Session lease and input state;
- a grant cannot cross Session or generation boundaries.

---

## 5. Security Properties

The implemented stage enforces:

1. Profile references never expose local storage paths.
2. One connection cannot change Agent identity in place.
3. Profile policy is checked before entering a Profile.
4. A Session write lease is exclusive to one Agent connection.
5. Different Profile Sessions can execute concurrently.
6. Global Tab and WebObject references bind Session and generation.
7. Cross-Session WebObject use fails before page operation execution.
8. Closed Session routes and leases are invalidated.
9. Monitor tokens bind Session, Profile and runtime generation.
10. The Monitor connects to the same real BrowserHost page rather than a duplicate page.
11. HumanControlLease and input cleanup remain Session-local.
12. One Session crash does not terminate other active Sessions.
13. Cookies, Storage values and raw credentials remain absent from Agent state and tools.
14. The default MCP surface remains exactly five tools.

---

## 6. Tests Added

New test coverage includes:

- connection identity immutability;
- Profile grant binding enforcement;
- Session lease exclusivity;
- global object relation projection;
- cross-Session object rejection;
- one backend screencast with multiple visual consumers;
- two concurrent Profile Sessions;
- cross-Session global Tab switching;
- same-Profile second-connection rejection;
- single-Session crash isolation;
- Session-local HumanControlLease;
- multi-Profile five-tool HTTP routing;
- specified-Session Monitor grants;
- Monitor generation mismatch rejection;
- MCP connection header and `profile_ref` schema.

Final Python result:

```text
477 passed
```

Only the two existing upstream deprecation warnings remain:

- `websockets.legacy`;
- Uvicorn's legacy WebSocket protocol import.

---

## 7. Remaining P12 Work

P12.4-P12.6 do not complete all P12 security re-scoping.

The next phase is:

```text
P12.7 P11 Re-scoping and Security Review
```

It must systematically bind and adversarially verify all P11 authority objects across Profile, connection, Session and runtime generation, including:

- SafetyContext;
- Step-up grants;
- LocalResourceGrant usage;
- selected payment references;
- payment and financial state;
- SafetyReceipt scope;
- protected instrument references;
- stale generation replay attempts.

P12.8 then performs complete acceptance, migration and maintenance review. Profile Bootstrap and Cookie import remain after P12 Core.

---

## Decision

P12.4-P12.6 are accepted.

WebFA now has a real multi-Profile, multi-Session routing core rather than a global browser singleton:

```text
Profile isolates internet identity.
Session isolates task runtime.
Connection and lease isolate Agent control.
Global routes isolate WebObjects and Tabs.
Monitor grants isolate human observation and control.
Runtime generation isolates old authority in time.
```
