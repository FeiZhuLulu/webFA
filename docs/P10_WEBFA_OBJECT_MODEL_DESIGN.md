# P10 WebFA Object Model

Status: design frozen; P10.0 through P10.7 complete

Implementation status:

- P10.0 Definition Freeze: complete
- P10.1 Schema Foundation: complete (`packages/schemas/web.py`)
- P10.2 Raw Snapshot Collector: complete (`browser/raw_snapshot.py`, `browser/raw_snapshot_collector.py`)
- P10.3 WebObjectCompiler: complete (`browser/web_object_compiler.py`)
- P10.4 Identity and ChangeSet: complete (`browser/object_registry.py`)
- P10.5 Queryable Observe: complete (`browser/web_observe.py`, internal `BrowserRuntime.observe_web()` path)
- P10.6 Semantic Operations: complete for the current BrowserHost capability surface (`browser/semantic_operations.py`, internal `BrowserRuntime.act_web()` path)
- P10.7 Structured Reading: complete (semantic form/list/table relations, AX subtree text normalization, real Chromium regression)
- P10.8 Opaque Surface and Human Takeover: next
- Current public Runtime remains on the BrowserState/P7 compatibility path until later migration phases

P10 is the next core architecture phase for WebFA. It does not add more browser-automation primitives. It upgrades WebFA from a DOM-element-oriented runtime into an agent-native web-object runtime.

Core rule:

> Define the complete product model first. Engineering may be delivered incrementally, but the target model must not be reduced into a disposable MVP.

## 1. Phase Goal

WebFA already proves the real browser loop:

```text
open_url -> observe -> act -> observe
```

It also has Managed Chromium, persistent profile state, object-level operations, authentication takeover, Visualizer, frames, dialogs, URL policy, structured errors, and an active-agent lease.

The remaining architectural mismatch is:

```text
Agent-facing behavior is becoming semantic,
but the public state model is still centered on DOM-like elements and a global action enum.
```

P10 completes these migrations:

```text
DOM element          -> WebObject
global action enum   -> object capabilities
click/type/press      -> internal execution primitives
full-page state dump -> queryable WebState
stale element        -> identity, version, and ChangeSet
unknown visual area  -> opaque_surface and human takeover
```

P7 is the first semantic-operation validation. P10 is its formalization, not a restart.

## 2. Product Boundary

WebFA is an agent-native browser runtime.

The agent should consume:

- WebObjects
- object state
- object relations
- object capabilities
- semantic operations
- document revisions
- object versions
- structured changes

The agent should not consume:

- raw DOM or full HTML
- selectors, XPath, or locators
- raw CDP or arbitrary evaluate
- browser coordinates
- screenshots as the normal action path
- Playwright concepts
- site-specific business actions

WebFA remains non-intelligent infrastructure. The Object Compiler is deterministic and rule-based. It must not contain an LLM, planner, suggested actions, or site-specific business understanding.

## 3. Target Runtime Structure

```text
Agent
  -> MCP / plugin
  -> open_url / observe / act / get_tabs / switch_tab

WebFA Runtime
  -> WebState
  -> ObjectRegistry
  -> SemanticOperationExecutor
  -> Session / lease / safety / takeover

WebObjectCompiler
  -> accessibility evidence
  -> DOM evidence
  -> layout and visibility evidence
  -> form and control state
  -> frame tree
  -> page lifecycle

BrowserHost
  -> Managed Chromium

Browser Engine
  -> Chromium / Blink / V8
```

The default MCP surface remains five tools.

## 4. WebState

`BrowserState` evolves into `WebState`. A compatibility alias may exist during migration, but the new protocol is defined by WebState.

```json
{
  "session_id": "session_default",
  "document_id": "doc_01",
  "document_revision": 143,
  "url": "https://example.com/search?q=webfa",
  "title": "Search results",
  "status": "idle",
  "outline": [],
  "regions": [],
  "objects": [],
  "object_count": 126,
  "frames": [],
  "dialogs": [],
  "auth": {},
  "takeover": {},
  "security": {},
  "agent": {},
  "changes": null,
  "errors": []
}
```

`objects` contains only the objects requested by the current observe mode. Page observation must not always serialize the complete object registry.

## 5. WebObject Type System

P10 uses two levels: a stable category and a concrete semantic role.

### Categories

```text
document
container
content
interactive
collection
dialog
frame
resource
opaque_surface
```

### Roles

Document and regions:

```text
document main region navigation header footer section article complementary
```

Readable content:

```text
heading paragraph text code quote image figure
```

Interactive objects:

```text
link button field searchbox textbox textarea checkbox radio switch
combobox option slider tab menu menuitem
```

Forms and tools:

```text
form toolbar upload_target
```

Collections and structured data:

```text
collection list list_item table row cell tree tree_item feed
```

State surfaces:

```text
dialog alert status tooltip
```

Frames and resources:

```text
frame download media resource
```

Unknown areas:

```text
opaque_surface
```

The complete role system is defined now; compiler coverage may expand phase by phase.

## 6. WebObject Schema

```json
{
  "id": "obj_42",
  "category": "interactive",
  "role": "link",
  "name": "FeiZhuLulu/webFA",
  "description": "",
  "text": "",
  "value": null,
  "state": {
    "visible": true,
    "enabled": true,
    "focused": false,
    "selected": null,
    "checked": null,
    "expanded": null,
    "required": null,
    "readonly": null,
    "busy": false,
    "invalid": null,
    "pressed": null
  },
  "relations": {
    "parent": "collection_results",
    "children": [],
    "belongs_to": "collection_results",
    "labelled_by": [],
    "described_by": [],
    "controls": [],
    "controlled_by": [],
    "form": null,
    "submit_control": null
  },
  "capabilities": ["open"],
  "observable": {
    "inspectable": true,
    "range_readable": false
  },
  "origin": "https://github.com",
  "frame_id": "frame_main",
  "version": 7,
  "lifetime": "document",
  "security": {
    "content_trust": "untrusted",
    "cross_origin": false
  }
}
```

Valid lifetimes:

```text
runtime session document frame transient
```

## 7. Capability Registry

Capabilities are semantic mutation or navigation operations attached to objects.

```text
open
open_in_new_context
activate
set_value
clear_value
choose
toggle
submit
expand
collapse
dismiss
download
upload
request_human_takeover
```

Reading is not an act capability. `inspect`, query, collection ranges, and changes belong to `observe`.

Capability descriptors are registered centrally so object summaries return capability names instead of repeating complete schemas.

```json
{
  "name": "set_value",
  "arguments": {
    "value": {"type": "string"}
  },
  "effect": "local_state_change",
  "requires_confirmation": false
}
```

P10 reserves effect metadata for P11 safety without implementing the full policy engine:

```text
read
navigation
local_state_change
external_write
external_send
download
upload
destructive
permission_change
unknown
```

## 8. Queryable Observe

`webfa.observe` remains one tool and gains structured modes.

### Page

```json
{"mode": "page"}
```

Returns document metadata, outline, major regions, priority object summaries, object count, frames, dialogs, auth, security, and current revision.

### Object

```json
{"mode": "object", "target": "collection_results"}
```

Returns full object state, relations, capabilities, version, and bounded child summaries.

### Query

```json
{
  "mode": "query",
  "query": {
    "category": "interactive",
    "role": "link",
    "name_contains": "webFA",
    "within": "collection_results",
    "capability": "open",
    "visible": true
  },
  "limit": 20
}
```

Supported query fields:

```text
id category role name name_contains text_contains within capability
visible enabled frame_id origin
```

CSS selectors, XPath, JavaScript predicates, and arbitrary expressions are forbidden.

### Changes

```json
{"mode": "changes", "since_revision": 142}
```

```json
{
  "from_revision": 142,
  "to_revision": 144,
  "added": [{"id": "dialog_2", "role": "dialog"}],
  "updated": [{
    "id": "field_search",
    "from_version": 3,
    "to_version": 4,
    "changed_fields": ["value"]
  }],
  "removed": [],
  "invalidated": []
}
```

Collection ranges also use observe:

```json
{
  "mode": "object",
  "target": "collection_results",
  "range": {"start": 20, "limit": 20}
}
```

Detail levels:

```text
summary standard full debug
```

Debug provenance is local/Visualizer-only by default.

## 9. Semantic Act

```json
{
  "target": "field_search",
  "operation": "set_value",
  "arguments": {"value": "webFA"},
  "expected_object_version": 3
}
```

Response:

```json
{
  "ok": true,
  "target": "field_search",
  "operation": "set_value",
  "previous_object_version": 3,
  "current_object_version": 4,
  "document_revision": 144,
  "state": {}
}
```

The Runtime chooses the internal implementation. For example, `activate` may use native activation, Enter, Space, or click internally. The agent does not choose the primitive.

Formal errors:

```text
object_not_found
object_stale
object_version_conflict
operation_not_supported
operation_temporarily_unavailable
operation_failed
document_changed
human_takeover_required
approval_required
```

Each error includes a code, message, target, operation, current object version, current document revision, and recover hint when applicable.

## 10. Identity, Version, and Revision

Identity hierarchy:

```text
runtime_id
session_id
document_id
frame_id
object_id
object_version
document_revision
```

Object identity reconciles multiple deterministic signals:

- frame identity
- AX node identity when available
- backend node identity when available
- native node continuity
- role and accessible name
- structural parent
- form membership
- collection membership
- deterministic structural fingerprint

No single signal such as `data-webfa-id`, DOM path, role/name, text, or item index is sufficient by itself.

Object versions increase for meaningful object changes such as value, selected state, checked state, expansion, enabled state, visibility, destination, capabilities, semantic role, name, or child membership.

Document revisions increase for meaningful semantic changes such as navigation, document replacement, object addition/removal, primary structure changes, dialog/auth/takeover changes, collection data changes, and important operability changes.

Animation frames, cursor blinking, decorative style changes, clocks, unimportant counters, and layout jitter do not normally increase the document revision.

Low-risk operations use optimistic concurrency. High-risk operations and explicit `expected_object_version` requests use strict version checks. Object-level conflicts are preferred over whole-document conflicts.

## 11. RawWebSnapshot

`RawPageSnapshot` evolves into an internal `RawWebSnapshot` containing:

```text
document metadata
navigation state
frame tree
accessibility evidence
DOM evidence
layout and visibility evidence
focus state
form and control state
collection and table evidence
dialogs
auth indicators
runtime status
```

Raw evidence never becomes the normal agent protocol.

## 12. WebObjectCompiler

Current responsibilities in `observe_probe`, `AgentViewBuilder`, `ElementRegistry`, and Runtime object actions evolve into:

```text
RawSnapshotCollector
WebObjectCompiler
ObjectRegistry
ChangeTracker
SemanticOperationExecutor
```

Compilation pipeline:

```text
collect raw evidence
-> normalize nodes
-> merge AX / DOM / layout / runtime evidence
-> classify category and role
-> calculate name and description
-> establish relations
-> derive capabilities
-> reconcile identity
-> compare previous snapshot
-> emit WebState and ChangeSet
```

The compiler stores debug provenance, for example AX node id, backend node id, native tag, name source, and applied compiler rules. Provenance is not included in normal agent output.

## 13. Structured Reading

P10 must formally cover:

- document outline and reading order
- article and section structure
- navigation, tabs, menus, and link groups
- forms and their fields/submit controls
- collections and bounded ranges
- tables, columns, rows, cells, and sorting state
- dialogs, alerts, status messages, and tooltips
- same-origin frame objects and cross-origin frame boundaries

Collections and tables must not be reduced to newline-split text.

## 14. Opaque Surface

When WebFA cannot reliably compile a region, it returns an explicit object:

```json
{
  "id": "opaque_1",
  "category": "opaque_surface",
  "role": "opaque_surface",
  "name": "Diagram editor",
  "reason": "semantic_structure_unavailable",
  "state": {"visible": true},
  "capabilities": ["request_human_takeover"]
}
```

Typical cases include canvas editors, remote desktops, games, and custom-drawn controls without usable semantics.

P10 does not add screenshot-coordinate fallback.

## 15. Human Takeover

The Auth Surface evolves toward a general Human Takeover Surface.

Reasons:

```text
authentication
captcha
opaque_surface
high_risk_confirmation
permission_request
file_selection
ambiguous_state
manual_identity_confirmation
```

```json
{
  "required": true,
  "reason": "opaque_surface",
  "target": "opaque_1",
  "origin": "https://example.com",
  "resume_operation": "observe"
}
```

P10 implements the contract and auth/opaque cases. P11 connects the full high-risk approval policy.

## 16. Playwright Removal

P10 does not maintain a Playwright fallback.

Remove during migration:

- PlaywrightBrowserDriver
- Playwright dependency
- `WEBFA_BROWSER_DRIVER=playwright`
- driver-factory Playwright branch
- Playwright-specific tests and parity documentation

Managed Chromium becomes the only formal BrowserHost path. This avoids maintaining two snapshot models and two action semantics while introducing the Web Object Model.

## 17. Compatibility

Default MCP tools remain:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Legacy `webfa.observe()` is equivalent to `{"mode":"page"}` during migration.

Existing P7 semantic actions may be translated for one explicit compatibility period. The old schema is deprecated and receives no new actions. `click`, `type`, and `press` do not become capabilities in the new model.

## 18. Code Migration Map

| Current | P10 target |
|---|---|
| BrowserState | WebState |
| BrowserElement | WebObject |
| BrowserContentBlock | content objects and outline |
| BrowserForm | form object and relations |
| RawPageSnapshot | RawWebSnapshot |
| AgentViewBuilder | WebObjectCompiler |
| ElementRegistry | ObjectRegistry |
| BrowserActionName | SemanticOperationName |
| Runtime `_object_action` | SemanticOperationExecutor |
| observe_probe | transitional RawSnapshotCollector |
| data-webfa-id | compatibility/debug hint |
| Playwright driver | removed |

Suggested structure:

```text
packages/webfa-core/browser/
  raw_snapshot/
    models.py
    collector.py
  objects/
    models.py
    categories.py
    roles.py
    capabilities.py
    compiler.py
    identity.py
    registry.py
    changes.py
  operations/
    models.py
    executor.py
    strategies/
  runtime.py
  session.py
  managed_chromium_host.py
```

## 19. Engineering Phases

### P10.0 Definition Freeze

Update AGENTS, core definition, direction document, README, Agent Manual, roadmap, and this design. Freeze terminology and clearly describe P7 as the first semantic-operation stage.

### P10.1 Schema Foundation

Add WebState, WebObject, category/role enums, object state/relations, capability descriptors, observe requests, query schema, ChangeSet, and semantic act requests/results. These schemas express the complete model even where compiler coverage is not yet implemented.

### P10.2 Raw Snapshot Collector

Collect Managed Chromium evidence for documents, frames, accessibility, DOM, layout, forms, controls, dialogs, and runtime state. No Playwright dependency and no raw evidence in agent output.

### P10.3 WebObjectCompiler

Implement deterministic category/role classification, names, relations, capabilities, outline, regions, and provenance. No LLM and no site-specific rules.

### P10.4 Identity and ChangeSet

Implement ObjectRegistry, stable identity reconciliation, object versions, document revisions, and compact changes. Avoid SPA conflict storms.

### P10.5 Queryable Observe

Implement page, object, query, changes, detail levels, ranges, and result limits. Do not support selectors or arbitrary expressions.

### P10.6 Semantic Operations

Implement open, open_in_new_context, activate, set_value, clear_value, choose, toggle, submit, expand, collapse, dismiss, download, upload, and request_human_takeover.

Previously validated P7/P8 tasks must succeed without agent-visible click/type/press.

### P10.7 Structured Reading

Complete document, navigation, collection, table, form, dialog/status, and frame models.

### P10.8 Opaque and Takeover

Add opaque surfaces, generalized takeover contracts, and Visualizer support for unknown areas and takeover reasons.

### P10.9 Migration and Removal

Migrate old state/action models, remove agent-visible primitives from the formal schema, remove Playwright, unify docs/tests, and run full regression.

## 20. Test and Benchmark System

Gold fixtures must cover:

1. static article
2. heading outline
3. multi-region navigation
4. search-result collection
5. multi-field form
6. React controlled input
7. checkbox/radio/switch
8. combobox
9. table
10. virtual list
11. dialog
12. alert/status
13. same-origin iframe
14. cross-origin iframe
15. Shadow DOM
16. SPA rerender
17. transient toast
18. canvas opaque surface
19. duplicate role/name objects
20. semantic continuity through layout reordering

Each fixture defines expected objects, category, role, name, relations, capabilities, versions, revisions, operation outcomes, changes, identity stability, and forbidden fields.

Real-site regressions include GitHub, Wikipedia, MDN, Hugging Face, a complex React application, a table-oriented application, and a user-assisted authentication site.

Primary metrics:

```text
object precision and recall
role accuracy
name accuracy
capability accuracy
identity stability
ChangeSet precision
observe payload size
task completion rate
agent-visible primitive usage
```

The target for agent-visible primitive usage is zero.

## 21. Completion Criteria

P10 is complete only when:

1. Agents complete real tasks through WebObjects and semantic operations.
2. click/type/press are absent from the formal agent schema.
3. WebFA no longer depends on Playwright.
4. Managed Chromium continues to run real modern web pages.
5. observe supports page, object, query, and changes.
6. Objects have stable identities and versions.
7. Meaningful page changes produce ChangeSets.
8. Reading, navigation, forms, collections, tables, dialogs, and frames have formal models.
9. Unknown regions become opaque surfaces.
10. Screenshot-coordinate fallback is not added.
11. The compiler remains deterministic and non-intelligent.
12. The default MCP surface remains five tools.
13. Cookies, storage, tokens, passwords, raw DOM, HTML, selectors, XPath, raw CDP, and evaluate remain unavailable to agents.
14. Existing P7/P8 real tasks pass on the new model.
15. Visualizer displays objects, relations, capabilities, versions, and changes.
16. No P10 subphase introduces a disposable public model.

## 22. Relationship to Later Phases

P11 Real Task Safety consumes capability effects, object origins, content trust, operation metadata, and takeover contracts.

P12 Multi Session / Multi Profile consumes session ids, isolated ObjectRegistries, profile binding, and leases.

P13 Durable Trace / Resume consumes revisions, object versions, ChangeSets, semantic operations, and structured results.

## Decision

P10 is not Element Registry v2. It is the WebFA Object Model phase.

```text
Agent
  -> WebObjects
  -> Semantic Operations
  -> WebFA Runtime
  -> Managed Chromium Host
  -> Chromium Engine
```

This is the architecture of an agent-native browser rather than a renamed browser-automation wrapper.
