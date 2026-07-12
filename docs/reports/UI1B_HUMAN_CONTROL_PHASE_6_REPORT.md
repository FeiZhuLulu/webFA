# UI-1B HumanControlLease Phase 6 Report

Status: implementation complete; final validation and post-implementation maintenance review passed

## 1. Objective

Phase 6 replaces the duplicate-page Electron AuthSurface with temporary local control over the same BrowserHost page used by the Agent.

The invariant remains:

```text
one Runtime Session
one BrowserHost page target
one Profile and storage context
Agent semantic operations or a bounded local HumanControlLease
never a second target URL load for monitoring or takeover
```

Human control is a local Runtime control-plane capability. It is not an Agent tool and does not change the five-tool MCP surface.

## 2. HumanControlLease

The Runtime now owns an exclusive `HumanControlLeaseManager`.

A lease is bound to:

- the authenticated Monitor connection;
- Session ID;
- Profile ID;
- active tab ID;
- takeover reason;
- previously active Agent ID;
- acquisition and expiry timestamps.

Lifecycle states:

```text
active
released
aborted
expired
```

Only one connection may hold the lease. A second Monitor connection receives a deterministic `human_control_busy` error.

Lease termination occurs on explicit release, WebSocket disconnect, Monitor grant revoke, Monitor grant expiry, HumanControlLease expiry, Runtime shutdown, or an aborted control path.

Natural expiry is reconciled with the BrowserWorker. The Worker clears its explicit takeover marker, publishes `takeover_finished`, and restores the prior Agent lease. If the underlying page still presents an authentication surface, Runtime may correctly continue to report that a new takeover is required; this is page state, not stale lease state.

## 3. Agent control boundary

While HumanControlLease is active, Runtime rejects mutating Agent operations with HTTP 409 and code:

```text
human_control_active
```

Covered operations include:

- `open_url`;
- semantic `act`;
- legacy write operations when explicitly enabled;
- tab switching;
- BrowserHost restart;
- retired visible/auth-surface control paths.

Agent observation remains available. During explicit takeover, `webfa.observe` returns a protected `human_takeover` state and does not expose page objects, password values, OTPs, or the human input stream.

After release, Runtime refreshes WebState before Agent mutation resumes.

## 4. Same-page input forwarding

ManagedChromiumHost implements local input through the current page CDP connection:

```text
Input.dispatchMouseEvent
Input.dispatchKeyEvent
Input.insertText
```

Supported input classes:

- mouse movement;
- mouse button press and release;
- wheel scrolling;
- key down and key up;
- text insertion;
- clipboard paste through text insertion;
- IME composition commit.

Non-text keys use explicit virtual key codes, including Backspace, Tab, Enter, Escape, navigation keys, Delete, and printable-key fallbacks.

Input is dispatched below the BrowserDriver abstraction. No CDP method, coordinate action, or human input operation is exposed to the Agent.

## 5. Monitor protocol

The Session-scoped Monitor grant adds an optional permission:

```text
takeover
```

An authenticated Monitor WebSocket may send:

```text
human_control_acquire
human_input
human_control_release
ping
```

Without `takeover`, a control request closes the connection with a scoped authorization error.

Human input messages are validated and bounded. Unknown fields, unsupported event types, invalid coordinates, oversized text, malformed modifiers, and non-boolean flags are rejected.

The server never echoes input values. Control responses contain only lease identity, status, reason, and expiry metadata.

While a lease is active, MonitorGateway periodically refreshes Runtime state so same-page navigation, DOM transitions, document revision changes, and disappearance of authentication surfaces are reflected in the structured projection.

## 6. Monitor UI

The Session Monitor remains three-column and read-only by default.

When no lease is active:

```text
Canvas pointer events disabled
Agent control label shown
human input capture absent
```

When the user acquires control:

```text
Canvas pointer events enabled
HumanControlLease badge shown
Agent mutation paused
mouse coordinates mapped to BrowserHost viewport
hidden local input capture forwards keyboard, paste, and composition
explicit “complete and return to Agent” action shown
```

Mouse movement is coalesced through `requestAnimationFrame` to avoid flooding the local data plane. Delayed visual frames are still rejected by Session/Tab/Document binding.

The Monitor does not gain an address bar, navigation controls, browser history, DOM bridge, or general-purpose browser UI.

## 7. Sensitive-data boundary

HumanInputEvent hides printable key and text fields from object representation.

Input values do not enter:

- SessionEventBus payloads;
- Monitor state snapshots;
- visual frame metadata;
- Action Log;
- SafetyReceipt;
- Agent WebState during takeover;
- WebSocket control responses;
- error messages.

Real validation uses a protected password input. The human enters a secret and submits the form while holding the lease. Agent observation during takeover contains no secret. After successful submission, the protected form disappears and the Agent sees only the generic success state.

A website can intentionally render user-entered data into ordinary visible page content after takeover. That visible content is page state rather than transport leakage; WebFA cannot guarantee secrecy for values a site deliberately publishes outside protected fields.

## 8. AuthSurface retirement

The duplicate-page AuthSurface is permanently retired:

- Electron main no longer imports or creates AuthSurfaceManager;
- AuthSurface IPC handlers were removed;
- preload no longer exposes AuthSurface methods;
- Control Center no longer auto-opens or embeds a takeover page;
- the former Electron source is a non-functional compatibility stub with no Electron import, WebContentsView, or `loadURL`;
- the former Renderer viewport is a static deprecation notice;
- REST compatibility routes return `410 Gone` unconditionally;
- Visualizer takeover mode is now `monitor`.

There is no environment-variable escape hatch that restores duplicate-page loading.

## 9. Validation coverage

Unit tests cover:

- exclusive lease acquisition;
- connection and Session binding;
- release, disconnect, expiry, and cleanup queue;
- input validation;
- sensitive text exclusion from representation.

Protocol tests cover:

- Monitor takeover permission;
- acquisition and release responses;
- input forwarding without echo;
- disconnect cleanup;
- grant revoke and expiry behavior.

Real Managed Chromium tests cover:

- mouse, wheel, key, and text input;
- one page target before and after input;
- unchanged target identity;
- Agent mutation rejection while the lease is active;
- BrowserHost restart rejection during takeover;
- protected Agent observe during takeover;
- user form submission during takeover;
- same document continuity after release;
- Agent resume after release;
- natural lease expiry and Worker cleanup;
- no secret in SessionEventBus or Visualizer state.

A post-implementation concurrency, lifecycle, input-state, visual-pipeline, and sensitive-data review is recorded in:

```text
docs/reports/UI1B_PHASE_6_MAINTENANCE_REVIEW.md
```

## 10. Remaining boundaries

Phase 6 does not provide:

- multi-Session human leases;
- remote Monitor access;
- OS-native secure attention sequence;
- native file-picker forwarding;
- browser permission-dialog automation;
- hardware security-key emulation;
- durable lease recovery across Runtime restart;
- GPU shared-texture rendering.

Those are separate future design areas. HumanControlLease is currently local, single-Session, and intentionally bounded.

## 11. Final validation

```text
Python tests:           454 passed
Warnings:               2 existing upstream deprecation warnings
Renderer typecheck:     passed
Electron typecheck:     passed
Python package build:   passed
Contract tests:          40 passed
git diff --check:       passed
```

The warnings come from the installed `websockets` compatibility layer and Uvicorn's legacy WebSocket protocol import. They are unrelated to HumanControlLease.

The public MCP capability list remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```
