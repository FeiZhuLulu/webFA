# UI-1B Monitor Projection Architecture

Status: frozen target architecture; implementation phases 1-5 complete

## 1. Product boundary

The Session Monitor is not a browser and never owns a second copy of the target page.

The invariant is:

```text
WebFA BrowserHost is the only real page instance.
The Monitor is a read-only projection of Runtime state and BrowserHost visual output.
```

The Monitor must not:

- launch or expose a Chrome UI;
- load the target URL in an iframe, BrowserView, WebContentsView, or another browser context;
- duplicate cookies, local storage, login state, or page execution;
- infer Runtime state from pixels;
- add address-bar, history, bookmarks, extensions, or normal human-browser navigation;
- expose screenshot-coordinate actions to Agents;
- add MCP tools.

The Monitor may be closed, hidden, or never opened. Agent browsing must continue normally.

## 2. Target architecture

```text
Agent
  -> five MCP browser tools
  -> BrowserRuntime
       -> BrowserSession
       -> BrowserDriver
       -> BrowserHost (single real page)
       -> ObjectRegistry / WebState
       -> SafetyContext
       -> SessionEventBus
       -> VisualSurfaceProvider
       -> HumanControlLease (later phase)

Session Monitor
  -> MonitorGateway
       -> subscribe SessionEventBus
       -> subscribe VisualSurface frames
       -> request/release HumanControlLease
       -> approve/reject current scoped step-up
```

The data plane has two independent streams:

```text
Structured event stream: what happened and what Runtime knows.
Visual frame stream: what the BrowserHost currently renders.
```

Pixels are never the source of truth for Runtime state.

## 3. SessionEventBus

### 3.1 Purpose

`SessionEventBus` is the internal ordered event journal for one or more browser sessions. It supports live subscribers and bounded replay for a future MonitorGateway.

### 3.2 Event identity

Every event contains:

```text
event_id
sequence
session_id
type
timestamp
tab_id?
document_id?
operation_id?
data (secret-free metadata only)
```

Sequence numbers are monotonically increasing within the bus. Consumers use sequence numbers for replay and gap detection.

### 3.3 Target event vocabulary

```text
session_started
session_closed
navigation_started
navigation_committed
navigation_failed
loading_changed
document_changed
tab_created
tab_switched
tab_closed
operation_started
operation_completed
operation_failed
safety_decision_changed
takeover_required
takeover_started
takeover_finished
visual_stream_started
visual_stream_stopped
frame_available
browser_crashed
```

Implementation coverage may expand incrementally, but this vocabulary is the stable internal target.

### 3.4 Security

Event payloads must not contain:

- passwords, OTPs, cookies, tokens, payment secrets;
- local absolute file paths;
- raw HTML or DOM snapshots;
- arbitrary Agent-controlled free text where a stable reference is sufficient;
- visual frame bytes.

Visual frames travel through the visual stream, not the event journal.

## 4. VisualSurfaceProvider

### 4.1 Purpose

`VisualSurfaceProvider` projects the single BrowserHost render surface into versioned frames. It is Runtime-internal and not an Agent capability.

### 4.2 Stable interface

```text
start_stream(binding_provider, config, frame_sink) -> stream_id
stop_stream(stream_id)
status(stream_id?)
close()
```

The provider wraps a replaceable host backend.

### 4.3 Binding

Each emitted frame is stamped at delivery time with the current Runtime binding:

```text
session_id
tab_id
document_id
```

This prevents the Monitor from confusing delayed frames from a previous document with the current document.

### 4.4 Frame model

```text
stream_id
frame_seq
session_id
tab_id
document_id
host_target_id?
host_frame_id?
format
width
height
device_scale_factor
scroll_offset_x
scroll_offset_y
captured_at
data (bytes)
```

Frame bytes are intentionally separate from JSON event payloads.

### 4.5 Stream configuration

```text
format: jpeg | webp | png
quality
max_width
max_height
every_nth_frame
```

Defaults optimize monitoring, not human browsing:

```text
jpeg
quality 70
1280 x 720
every frame delivered by backend
```

Later MonitorGateway policy controls idle/burst/takeover frame rates.

## 5. Host backend boundary

A BrowserHost may expose a visual backend, but the BrowserHost itself remains unaware of Monitor UI and Agent protocol.

```text
ManagedChromiumHost
  -> CDP screencast backend (experimental implementation)

Future ElectronOffscreenBrowserHost
  -> offscreen bitmap/shared-texture backend

Future native host
  -> engine compositor surface backend
```

CDP details must remain below the provider abstraction.

## 6. Managed Chromium screencast experiment

The first backend uses the same hidden WebFA-managed Chromium page target already used by the Agent runtime.

```text
same Chromium process
same page target
same Profile
same cookies and storage
same renderer
separate internal CDP connection dedicated to visual frames
```

It does not create another page and does not open Chrome UI.

The experiment uses:

```text
Page.startScreencast
Page.screencastFrame
Page.screencastFrameAck
Page.stopScreencast
```

Because these CDP methods are experimental, the backend is replaceable and no public protocol may depend on them.

The screencast connection runs on a dedicated reader thread so it cannot interfere with the command connection used for navigation, observation, and actions.

Every received frame must be acknowledged even when the consumer rejects or fails to process it.

## 7. Runtime integration

`BrowserRuntime` owns the SessionEventBus.

The worker publishes deterministic Runtime events around:

- session start and close;
- navigation start/commit/failure;
- semantic operation start/complete/failure;
- document identity or revision change;
- tab switch;
- Human Takeover transitions;
- visual stream start/stop and frame availability.

The Runtime exposes internal Python methods for tests and the MonitorGateway. No Agent REST or MCP capability is added.

## 8. MonitorGateway and local transport

### 8.1 Trust boundary

The Control Center owns the high-privilege Visualizer control token. It may ask the Runtime to issue a short-lived Monitor grant for the active Session.

A Monitor grant is:

```text
high entropy
one-time authentication
session scoped
permission scoped: events and/or frames
short lived
revocable
not stored in the URL
not stored in localStorage
```

The Runtime stores only a SHA-256 digest of the raw token. A token can authenticate exactly one WebSocket connection. Closing the connection releases the grant; revoking the grant terminates an active connection.

The Monitor preload does not expose the Visualizer control token, Runtime start/stop, policy editing, payment tools, resource grants, or Step-up approval.

### 8.2 Local WebSocket protocol

The local Monitor connection uses one WebSocket:

```text
JSON text frames
  -> monitor_ready
  -> session_event
  -> state_snapshot

binary frames
  -> 4-byte network-order JSON-header length
  -> UTF-8 JSON frame metadata
  -> compressed image bytes
```

The token is sent in the first authentication message, never in the WebSocket URL. The server validates the local Renderer Origin before accepting Monitor data.

The connection is read-only after authentication. Any application-level client message closes the connection. Human input is not part of phases 4-5.

### 8.3 State projection

The Gateway sends a safe initial Runtime snapshot and refreshes that snapshot after navigation, document changes, tab switches, operation completion, safety transitions, and takeover transitions.

Snapshot URLs remove query strings and fragments before leaving the Runtime. This prevents OAuth codes, tokens, or other URL secrets from entering the Monitor UI.

### 8.4 Electron Monitor window

The Session Monitor is a separate Electron BrowserWindow with a separate preload and a limited IPC surface:

```text
get short-lived Monitor configuration
open Control Center
```

The window loads only the local Monitor UI route. It never loads the target page. Navigation and new windows are locked to the local Console origin. DevTools are disabled for this limited window.

### 8.5 Canvas projection

The center surface decodes binary JPEG/PNG/WebP packets and draws them onto a non-interactive Canvas.

The consumer rejects delayed frames when their Session, Tab, or Document binding no longer matches the selected Runtime snapshot. When the document identity changes, the previous Canvas is cleared before a new matching frame is shown.

The left and right sidebars are independent structured projections. Pixels are not used to infer URL, Agent action, SafetyContext, or task state.

## 9. State-change model

The Monitor updates from both streams:

```text
SessionEventBus
  -> URL/title/loading/activity/safety/takeover labels

VisualSurfaceProvider
  -> center visual surface only
```

A `frame_available` event contains frame metadata and sequence only. The actual frame bytes are delivered through the frame sink.

Consumers discard a frame when its session/tab/document binding no longer matches the selected Monitor context.

## 10. Human Takeover boundary

Human input is not part of phases 1-3.

The final model will add `HumanControlLease`:

```text
Agent lease paused
-> human lease acquired for same BrowserHost page
-> Monitor forwards local input to same host
-> sensitive input excluded from Agent state
-> human lease released
-> Runtime observes updated page
-> Agent lease resumes
```

The current Electron `AuthSurface` that loads a URL in a separate WebContentsView is transitional and is not the final architecture.

## 11. Phase plan

### Phase 1: SessionEventBus — complete

Implemented:

- typed event model;
- thread-safe publish/subscribe;
- bounded replay;
- Runtime ownership;
- deterministic Runtime event emission;
- unit and integration tests.

### Phase 2: VisualSurfaceProvider — complete

Implemented:

- stable frame/config/binding models;
- backend protocol;
- provider adapter;
- Runtime-internal start/stop/status methods;
- event integration;
- unit tests using a fake backend.

### Phase 3: ManagedChromiumHost screencast experiment — complete

Implemented:

- dedicated CDP screencast connection and thread;
- start/stop lifecycle;
- frame decoding and metadata normalization;
- mandatory frame acknowledgement;
- HostBrowserDriver backend exposure;
- real Managed Chromium integration test;
- screenshot fallback remains available.

### Phase 4: MonitorGateway and Session-scoped Token — complete

Implemented:

- one-time short-lived Monitor capabilities;
- token digest storage and bounded grant history;
- active connection revoke and release lifecycle;
- local Origin enforcement;
- ordered event replay and live structured snapshots;
- read-only WebSocket protocol;
- separate Electron Monitor preload and IPC boundary.

### Phase 5: Binary frame transport and Monitor Canvas — complete

Implemented:

- JSON and binary multiplexing over one local WebSocket;
- versioned binary frame packet;
- bounded event and latest-frame queues;
- three-column Session Monitor route;
- independently collapsible sidebars;
- non-interactive Canvas rendering;
- delayed-frame Session/Tab/Document rejection;
- automatic short-lived grant refresh after disconnect;
- real Managed Chromium end-to-end transport validation.

### Phase 6: HumanControlLease — next

Planned:

- pause Agent lease;
- acquire time-bounded human control over the same BrowserHost page;
- forward local mouse, keyboard, wheel, and composition input;
- exclude sensitive values from Agent state and audit payloads;
- release the human lease and re-observe before Agent resume;
- remove the transitional duplicate-page AuthSurface.

## 12. Acceptance criteria for phases 1-5

- The default MCP tool list remains exactly five tools.
- No target URL is loaded by Electron Monitor code.
- Starting a visual stream does not create a second page target.
- Closing the visual stream does not close or mutate the Agent page.
- Frames come from the same ManagedChromiumHost page target.
- Session events are ordered and replayable.
- Slow or failing frame consumers do not block or break Agent operations.
- Every CDP screencast frame is acknowledged.
- Frame metadata includes current session/tab/document binding.
- Frame data and events contain no credentials, tokens, local paths, raw DOM, or raw HTML.
- Existing P10/P11 behavior and tests remain green.
- The Monitor token never appears in the URL or localStorage.
- The Monitor preload cannot access the Visualizer control token or long-term policy APIs.
- Revoking a Monitor grant terminates the active connection.
- Binary frames are bound to Session, Tab, and Document identity.
- The Canvas is non-interactive and the Monitor never loads the target URL.
- Closing the Monitor stops the visual stream without closing or mutating the Agent page.
- Python tests, renderer/electron typechecks, package build, and `git diff --check` pass.

## 13. References

- Chrome DevTools Protocol Page domain: `Page.startScreencast`, `Page.screencastFrame`, `Page.screencastFrameAck`, and `Page.stopScreencast` are experimental.
- Electron Offscreen Rendering remains a candidate future BrowserHost backend, not a Monitor-owned page.
