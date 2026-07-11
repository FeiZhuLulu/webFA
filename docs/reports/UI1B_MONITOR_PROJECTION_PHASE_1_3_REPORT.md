# UI-1B Monitor Projection Phases 1-3 Report

Status: complete

## Scope

This delivery implements the first three internal phases of the frozen Session Monitor projection architecture:

```text
1. SessionEventBus
2. VisualSurfaceProvider
3. ManagedChromiumHost screencast experiment
```

It does not implement Monitor UI transport, Human Takeover input, or a new public protocol.

## Product invariant

The implementation preserves the central WebFA boundary:

```text
BrowserHost is the only real page instance.
Session Monitor is only a projection.
```

No iframe, Electron WebContentsView, Chrome window, duplicate browser page, or second target URL load was added.

## Phase 1: SessionEventBus

Added:

```text
packages/webfa-core/browser/session_events.py
```

Capabilities:

- monotonic event sequence;
- stable event IDs;
- thread-safe publication;
- bounded replay journal;
- session filtering;
- asynchronous live subscribers;
- bounded subscriber queues;
- callback failure isolation;
- binary-frame rejection;
- sensitive-key rejection.

The stable internal event vocabulary includes session, navigation, document, tab, operation, safety, takeover, visual-stream, frame, and crash events.

BrowserRuntime now owns the event bus and emits implemented events for:

- session start and close;
- navigation start, commit, and failure;
- document revision changes;
- semantic operation start, completion, and failure;
- safety-decision changes;
- Human Takeover requests;
- tab switches;
- visual stream start/stop;
- frame availability;
- BrowserHost crashes.

Frame bytes never enter the event journal.

## Phase 2: VisualSurfaceProvider

Added:

```text
packages/webfa-core/browser/visual_surface.py
```

The stable abstraction contains:

- `VisualStreamConfig`;
- `VisualSurfaceBinding`;
- `HostVisualFrame`;
- `VisualFrame`;
- `VisualSurfaceBackend` protocol;
- `VisualSurfaceProvider` protocol;
- `BoundVisualSurfaceProvider` implementation.

The provider stamps every delivered frame with the current:

```text
session_id
tab_id
document_id
```

Host frame collection and Monitor frame consumption are decoupled by a bounded delivery queue. Slow or failing sinks do not block the BrowserHost or Agent operation thread. Old queued frames are dropped in favor of newer frames.

`frame_available` events contain metadata only. Binary frame data is delivered exclusively to the frame sink.

BrowserRuntime exposes internal Python methods:

```text
start_visual_stream
stop_visual_stream
visual_stream_status
subscribe_session_events
unsubscribe_session_events
replay_session_events
```

These methods are not exposed through REST or MCP.

## Phase 3: Managed Chromium screencast experiment

Updated:

```text
packages/webfa-core/browser/managed_chromium_host.py
packages/webfa-core/browser/host_driver.py
```

The experiment uses:

```text
Page.startScreencast
Page.screencastFrame
Page.screencastFrameAck
Page.stopScreencast
```

Implementation properties:

- uses the same WebFA-managed Chromium process;
- uses the same page target as Agent operations;
- creates a separate internal CDP connection only for frame transport;
- does not create another page target;
- does not display Chrome UI;
- runs frame reception on a dedicated daemon thread;
- decodes compressed image data to bytes;
- normalizes viewport and scroll metadata;
- acknowledges every received frame in `finally`;
- keeps screenshot capture as a fallback capability;
- stops the stream before BrowserHost shutdown;
- reports stream lifecycle and frame count in host status.

CDP screencast supports JPEG and PNG. The general provider model also reserves WebP for future backends, but Managed Chromium rejects WebP explicitly.

## Document binding

Runtime invalidates the current visual document binding before navigation and refreshes it after the new WebState is compiled. Frames are therefore associated with the active WebFA document identity instead of being inferred from pixels.

Consumers must ignore frames whose session, tab, or document binding does not match the selected Monitor context.

## Tests

Added or expanded:

```text
tests/unit/test_session_events.py
tests/unit/test_visual_surface.py
tests/unit/test_managed_chromium_cdp.py
tests/integration/test_managed_chromium_driver.py
```

Validation covers:

- ordered replay and session filtering;
- subscriber failure isolation;
- event payload secret and binary rejection;
- current document binding on frame delivery;
- slow Monitor sink backpressure;
- mandatory screencast frame acknowledgements;
- real JPEG frame delivery from Managed Chromium;
- unchanged page-target count before and after streaming;
- Agent page remains operational after stream stop;
- Runtime event and visual-frame integration;
- no frame bytes in SessionEventBus.

Final validation:

```text
Python tests:           425 passed
Renderer typecheck:     passed
Electron typecheck:     passed
Python package build:   passed
git diff --check:       passed
```

Only the existing upstream `websockets` and `uvicorn` deprecation warnings remain.

## Public-interface check

The default MCP interface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

No monitor, frame, screenshot-coordinate, CDP, input, or takeover tool was added for Agents.

## Remaining work

The following are intentionally not included in phases 1-3:

1. `MonitorGateway` with a session-scoped control token;
2. binary local frame transport to the Electron Monitor;
3. adaptive frame-rate policy for hidden, idle, active, and takeover states;
4. Monitor canvas renderer and frame-gap handling;
5. `HumanControlLease` and same-page input forwarding;
6. replacement of the transitional duplicate-page Electron AuthSurface;
7. multi-session stream routing after P12.

The current screencast backend is experimental and replaceable. It is not part of the Agent-facing WebFA protocol.
