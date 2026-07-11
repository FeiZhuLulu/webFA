# P11.6 Local Resource Broker Report

Status: complete

## Goal

Allow an Agent to upload a user-approved local resource without exposing an arbitrary local path or the wider filesystem.

## Implemented

Added `LocalResourceBroker` with:

- opaque `resource_ref` identifiers;
- WebFA-managed resource copies;
- safe original display filename preservation;
- owner, purpose, and allowed-origin scope;
- Agent and Profile bindings;
- expiry and maximum-use controls;
- list, authorize, consume, and revoke lifecycle;
- 20 MiB initial resource limit.

The public resource projection contains metadata only. It never contains the WebFA backing path or original user filesystem path.

## Upload operation

File inputs now declare:

```text
upload(resource_ref, purpose?)
```

They no longer require coordinate interaction or an arbitrary path argument. The semantic executor rejects `path`, `file_path`, and legacy `resource_id` payloads.

Execution path:

```text
Agent upload request
  -> local_data_egress SafetyContext
  -> declaration resource/origin/purpose match
  -> LocalResourceBroker Agent/Profile/origin/purpose checks
  -> provider_verified evidence
  -> BrowserHost protected file injection
  -> resource use-count consumption
```

Managed Chromium uses `DOM.setFileInputFiles` internally. CDP details remain private to BrowserHost and are not exposed to the Agent protocol.

## Visualizer

Added local resource grant controls:

- choose a file;
- set owner and purpose;
- set target Origin;
- bind the current Agent and Profile;
- set expiry and use count;
- copy the opaque reference;
- revoke a grant.

The selected bytes are copied into a WebFA-managed resource directory. The website receives the approved display filename, while the Agent receives only `resource_ref`.

## Validation

Validated with real Managed Chromium:

- resource created through Visualizer API;
- no backing path returned;
- SafetyContext includes the exact resource reference and destination;
- file is injected into a real `<input type=file>`;
- the website observes the approved filename;
- resource becomes consumed after one use;
- Agent/Profile/origin/purpose mismatch is denied;
- invalid base64, empty resources, expiry, revoke, and use count are tested.

## Boundaries

The P11.6 grant index is session-local. Managed resource bytes are stored on disk, but grants are not restored after Runtime restart. Durable grant restoration belongs with later durable state/trace work. Consumed bytes are retained until revoke or cleanup so a website can still submit a form after file selection.
