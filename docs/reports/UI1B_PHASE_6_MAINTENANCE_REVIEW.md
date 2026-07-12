# UI-1B Phase 6 Post-Implementation Maintenance Review

Date: 2026-07-13

Status: review complete; identified defects fixed; final validation passed

## 1. Review scope

This review examined the uncommitted UI-1B Phase 6 HumanControlLease implementation after its initial functional acceptance.

The review focused on:

- Agent/Human control concurrency;
- lease acquisition, expiry, disconnect, revoke, and Runtime shutdown;
- same-page input-state cleanup;
- visual-frame identity and ordering;
- MonitorGateway authentication and queue semantics;
- Monitor renderer input, IME, pointer, and asynchronous image decoding;
- sensitive URL and audit-log projection;
- Electron privilege isolation;
- preservation of the five-tool Agent API.

The architectural invariant remains unchanged:

```text
BrowserHost owns the only real webpage instance.
Session Monitor is a projection and bounded local control surface.
Human input never becomes an Agent capability.
```

## 2. Correctness defects fixed

### 2.1 Legacy Agent mutation race

`BrowserRuntime.open()` and legacy `act()` checked HumanControlLease before entering the Runtime transaction lock. A lease could be acquired between the check and the actual browser mutation.

The complete check, AgentLease acquisition, and browser operation now execute under `_web_operation_lock`.

### 2.2 Expired-lease reacquisition race

A new HumanControlLease could be created before delayed cleanup of an expired lease had cleared the BrowserWorker takeover marker. The delayed cleanup could then clear the newly acquired takeover.

Lease expiry is now reconciled before acquisition. Idempotent acquisition by the same connection returns the existing lease without emitting a second `takeover_started` transition.

### 2.3 Same-connection scope confusion

Repeated acquisition by the same Monitor connection previously returned the current lease without validating its Session, Profile, tab, or reason.

Idempotency now requires an exact control scope. The previously active Agent ID is restoration metadata and is intentionally excluded from identity comparison because the Agent lease may expire while human control is active.

### 2.4 Tab-scoped lease enforcement

HumanControlLease was declared tab-scoped, but input dispatch only verified Session identity.

Every human input and structured-state synchronization now verifies that the Runtime's current tab still matches the lease tab. A mismatch produces `human_control_tab_mismatch` rather than applying input to another tab.

### 2.5 Stuck input after disconnect

If the Monitor disconnected while a mouse button or modifier key was held, BrowserHost might never receive the corresponding release event.

Runtime now tracks pressed pointer and keyboard state. Explicit release, disconnect, revoke, expiry, and Runtime shutdown synthesize bounded `mouse_up` and `key_up` events before ending takeover.

### 2.6 Runtime shutdown race

A lease expiring at the same instant as Runtime shutdown could make lease termination throw and skip normal BrowserHost closure.

Lease termination during shutdown is now best-effort and cannot prevent worker, BrowserHost, local-resource, and event-journal cleanup.

## 3. MonitorGateway fixes

### 3.1 Critical control-message isolation

Human-control state and error responses shared the bounded lossy event queue. An event backlog could displace lease-acquired or lease-released responses.

Control messages now use a separate prioritized queue. Runtime activity events and latest-frame delivery retain their independent bounded queues.

### 3.2 Invalid authentication payload no longer burns token

A malformed stream configuration was previously validated after consuming the one-time Monitor token.

`after_sequence` and stream configuration are now validated before token consumption. A rejected authentication attempt does not destroy an otherwise valid capability.

### 3.3 Takeover requires a visual surface

A Monitor grant could request `takeover` without `frames`, allowing blind coordinate input.

The capability compiler now requires `frames` whenever `takeover` is present. Human control acquisition and input are also rejected when BrowserHost visual-stream startup failed.

### 3.4 Natural expiry notification

When a lease expired naturally, Runtime released it but Monitor UI could remain in the active-control state.

MonitorGateway now tracks the connection's lease identity and emits an explicit inactive state plus refreshed Runtime snapshot when the lease disappears.

### 3.5 Deterministic disconnect cleanup

HumanControlLease is released first and synchronously when the WebSocket closes. Visual stream and event subscription are then stopped. This prevents a slow Screencast shutdown from unnecessarily extending Agent suspension.

## 4. Visual pipeline fixes

### 4.1 Frame/document misbinding

VisualSurfaceProvider previously read the current Session/Tab/Document binding in the delivery thread. A delayed old frame could therefore be stamped with a new document identity.

Binding is now captured atomically when the Host frame enters the provider queue. Delayed frames retain their original document identity and are rejected by the Monitor after navigation.

### 4.2 Asynchronous image decode ordering

Multiple `createImageBitmap()` operations may complete out of order. An older JPEG could finish after a newer frame and overwrite the Canvas.

The Monitor now uses a decode generation. A newer frame, document switch, or socket close invalidates all older in-flight decode results.

### 4.3 Event-journal flooding

`frame_available` was written for every visual frame. At normal frame rates this could evict navigation, operation, and safety events from the bounded SessionEventBus replay buffer.

Binary frame delivery remains full rate. Journal metadata is emitted for the first frame, on Session/Tab/Document binding changes, and at most once per second otherwise.

### 4.4 Stream resource limits

Visual stream dimensions and cadence previously had no practical upper bound.

Runtime now enforces integer-only configuration with:

```text
max width/height: 8192
quality: 0..100
everyNthFrame: 1..120
delivery queue: 1..32
```

NaN, Infinity, booleans used as integers, and oversized values are rejected.

## 5. Monitor renderer fixes

- Pointer Capture guarantees pointer-up delivery after dragging outside the Canvas.
- Pointer cancellation sends a final bounded `mouse_up`.
- Explicit return to Agent flushes active pointer state before lease release.
- Ctrl/Cmd+V is not dispatched to the remote page in addition to local paste insertion, preventing duplicate paste and remote clipboard access.
- IME composition suppression is time-bounded and cleared on inactive lease or disconnect.
- Hidden input contents, pending moves, timers, and pointer state are cleared when control ends.
- In-flight old visual-frame decodes cannot overwrite a newer frame.

## 6. Sensitive-data maintenance

### Monitor URL

Monitor snapshots already removed query strings and fragments. They now also redact:

- URL-decoded email-like path components;
- high-entropy path components;
- values following sensitive path markers such as `reset`, `token`, `invite`, `verify`, and compound forms such as `reset-password`.

### Action Log

URL fragments are now removed from ActionLog messages. This prevents OAuth implicit-flow tokens and SPA magic-link secrets from entering the local audit ring.

Human input values remain excluded from Runtime events, snapshots, receipts, errors, and control responses.

## 7. Electron hardening

The Control Center contains the high-privilege Visualizer control token. Its Renderer now runs with Electron sandboxing enabled in addition to:

- context isolation;
- disabled Node integration;
- origin-locked navigation;
- denied child windows;
- sender and frame-origin validation on privileged IPC.

The Session Monitor remains separately sandboxed and never receives the Visualizer control token.

## 8. Validation

```text
Python tests:           454 passed
Contract tests:          40 passed
Renderer typecheck:     passed
Electron typecheck:     passed
Python package build:   passed
MCP integration:        passed
MCP public tools:       exactly five
git diff --check:       passed
```

Two existing deprecation warnings remain in the installed `websockets` compatibility layer and Uvicorn's legacy WebSocket protocol import.

## 9. Remaining known boundaries

The following are not treated as defects in the current phase, but remain explicit future work:

- CDP `Page.startScreencast` remains an experimental backend capability behind VisualSurfaceProvider.
- HumanControlLease and Monitor grants are in-memory and do not survive Runtime restart.
- Multi-Session and Multi-Profile control isolation remains P12 work.
- Browser-native permission prompts, native file pickers, hardware security keys, and OS secure-attention flows are not generalized.
- Keyboard mapping covers common browser input but is not yet a complete OS-layout/media/dead-key abstraction.
- Only one Managed Chromium Screencast can currently be active; additional frame-consuming Monitor connections fail closed.
- The current disconnect path performs deterministic visual-stream cleanup on the local ASGI loop. A future dedicated shielded cleanup executor could reduce worst-case disconnect latency without weakening cleanup guarantees.
- A website may deliberately render entered information into ordinary visible content after submission; WebFA cannot classify such site-authored disclosure as transport leakage.

No remaining issue found in this review permits an Agent to access HumanControlLease input or adds a browser-control capability to the public Agent API.
