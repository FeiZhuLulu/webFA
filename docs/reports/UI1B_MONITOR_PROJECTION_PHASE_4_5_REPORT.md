# UI-1B Monitor Projection Phase 4-5 Report

Status: complete

Scope:

```text
Phase 4: MonitorGateway and Session-scoped Token
Phase 5: Local binary frame transport and Monitor Canvas
```

## Outcome

WebFA now has a real Session Monitor data path without creating a human browser or a second copy of the target page.

```text
Agent
  -> five MCP browser tools
  -> BrowserRuntime
       -> one BrowserHost page
       -> SessionEventBus
       -> VisualSurfaceProvider

Control Center
  -> issue short-lived Monitor grant

Session Monitor
  -> limited preload
  -> read-only local WebSocket
       -> JSON Runtime events and state snapshots
       -> binary visual frames
  -> non-interactive Canvas
```

The BrowserHost remains the only page owner. The Monitor never calls `loadURL` for the target website, never receives cookies or credentials, and never exposes coordinate actions to the Agent.

## Phase 4: MonitorGateway

### Session-scoped capability

Added:

```text
packages/webfa-core/browser/monitor_gateway.py
apps/runtime/api/monitor_access.py
apps/runtime/api/routes/monitor.py
```

A Monitor grant contains:

```text
grant_id
session_id
permissions: events and/or frames
issued_at
expires_at
one-time raw token
```

Security properties:

- 256-bit-class random bearer token;
- raw token returned only at issue time;
- Runtime stores only its SHA-256 digest;
- one token authenticates one connection;
- token is sent in the first WebSocket message, not in the URL;
- no localStorage persistence;
- 30-3600 second lifetime, default 300 seconds;
- explicit revoke support;
- active connection closes after revoke;
- normal disconnect releases the connection state;
- bounded terminal grant history;
- active Session binding checked before data delivery.

The grant issue/list/revoke endpoints are under the existing Visualizer control-token boundary:

```text
POST   /v1/visualizer/monitor-grants
GET    /v1/visualizer/monitor-grants
DELETE /v1/visualizer/monitor-grants/{grant_id}
```

These endpoints are Desktop control-plane APIs. They are not Agent tools.

### Read-only WebSocket

Added:

```text
/v1/monitor/ws
```

Authentication sequence:

```text
open local WebSocket
-> send authenticate message with one-time token
-> Runtime consumes token
-> verify active Session
-> return monitor_ready
-> begin event/frame projection
```

After authentication the channel is server-to-client only. Any application-level client message terminates the connection. Human input remains outside this phase.

The gateway enforces the configured local Renderer Origin. Electron passes the trusted Console origin to the Runtime through:

```text
WEBFA_MONITOR_ALLOWED_ORIGINS
```

### Structured state

The connection provides:

```text
monitor_ready
session_event
state_snapshot
```

The initial and refreshed snapshots include only Monitor-safe Runtime state:

```text
Session
Profile
active Agent
Agent lease expiry
Tab
document identity and revision
sanitized URL
title
object count
takeover state
```

URL query strings and fragments are removed before projection, preventing OAuth codes or query tokens from reaching the Monitor.

Snapshots are refreshed after:

- navigation commit;
- document change;
- tab switch;
- operation completion or failure;
- safety decision change;
- takeover state transition.

## Phase 5: binary visual transport

### Packet format

JSON events and image data share one WebSocket, but visual bytes are never base64-encoded into JSON.

Binary packet:

```text
4 bytes: big-endian JSON header length
N bytes: UTF-8 JSON metadata
remaining bytes: JPEG / PNG / WebP payload
```

Metadata includes:

```text
protocol version
stream_id
frame_seq
session_id
tab_id
document_id
format
width / height
device scale factor
scroll offsets
capture time
```

Header size is limited to 64 KiB and frame payload to 16 MiB.

### Backpressure

The gateway separates:

```text
ordered event queue: 256 entries
latest visual frame queue: 2 entries
```

If the Monitor is slow:

- old visual frames are discarded in favor of recent frames;
- Agent operations and BrowserHost screencast acknowledgement continue;
- simultaneous event and frame readiness does not discard either message;
- disconnect cleanup deterministically stops the visual stream.

### Electron isolation

Added:

```text
apps/desktop/electron/monitorPreload.ts
apps/desktop/renderer/src/app/monitor/page.tsx
apps/desktop/renderer/src/app/monitor/monitor.module.css
```

The Session Monitor runs in a separate Electron `BrowserWindow` with:

- separate limited preload;
- context isolation;
- Node integration disabled;
- sandbox enabled;
- DevTools disabled;
- local navigation lock;
- new-window denial.

The Monitor preload exposes only:

```text
get short-lived Monitor configuration
open the Control Center
```

It does not expose:

- Visualizer control token;
- Runtime/MCP start-stop;
- Profile or policy editing;
- payment-instrument management;
- local-resource grants;
- Step-up approval;
- AuthSurface control.

### Canvas projection

The center region decodes image bytes with `createImageBitmap` and draws onto a Canvas.

The Canvas is explicitly non-interactive:

```text
pointer-events: none
```

It has no address bar, page navigation, browser history, target iframe, WebContentsView, or DOM interaction bridge.

The Monitor rejects delayed frames when their binding differs from the current:

```text
Session
Tab
Document
```

When the structured document identity changes, the previous Canvas is cleared before a new matching frame is displayed.

The left and right sidebars remain independently collapsible. Their state comes from Runtime snapshots and Session events, not from image analysis.

## Real Managed Chromium validation

The end-to-end integration test performs:

```text
open real fixture in ManagedChromiumHost
-> issue Monitor grant
-> authenticate local WebSocket
-> receive monitor_ready
-> receive JPEG binary packet
-> verify frame document_id equals Runtime document_id
-> close Monitor
-> call Agent observe on the same Runtime page
```

Validated properties:

- frame begins with JPEG signature;
- frame Session and Document match the Agent Runtime;
- query token in the opened URL is absent from the Monitor snapshot;
- closing the Monitor stops the visual stream;
- the Agent page remains alive and observable;
- no second target page is introduced by the Monitor data path.

The same-target invariant continues to be covered by the Phase 3 Managed Chromium target-count test.

## Public interface

The Agent interface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

No Monitor, frame, screenshot, coordinate, WebSocket, CDP, or approval tool was added to MCP.

## Validation

Covered by:

```text
tests/unit/test_monitor_gateway.py
tests/integration/test_monitor_gateway_api.py
tests/integration/test_managed_chromium_driver.py
tests/contract/test_electron_runtime_contract.py
```

Final acceptance:

```text
Python tests:          436 passed
Renderer typecheck:    passed
Electron typecheck:    passed
Python package build:  passed
git diff --check:      passed
```

The only warnings are the existing upstream deprecations from `websockets` and `uvicorn`.

## Remaining boundary

The Monitor is read-only. It cannot yet:

- pause the Agent lease;
- acquire human control;
- forward mouse, keyboard, wheel, touch, or IME input;
- perform authentication or payment verification on the same page;
- replace the transitional duplicate-page AuthSurface.

Those capabilities belong exclusively to Phase 6:

```text
HumanControlLease
```

Phase 6 must preserve the same invariant:

> Human input is temporarily forwarded to the existing BrowserHost page; the Monitor never becomes a second browser.
