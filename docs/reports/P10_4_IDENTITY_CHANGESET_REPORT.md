# P10.4 Identity and ChangeSet Report

Date: 2026-07-11

## Status

P10.4 is complete.

WebFA now has an internal ObjectRegistry that reconciles successive WebObjectCompiler outputs into stable session-scoped object identities, object versions, document revisions, and compact ChangeSets.

## Delivered

- `ObjectRegistry`
- stable `obj_N` identities owned by the registry rather than compiler-local IDs
- identity reconciliation priority:
  1. Chromium engine frame identity
  2. backend DOM node identity
  3. accessibility node identity
  4. persistent WebFA legacy element evidence during migration
  5. unique semantic and structural fallback
- ambiguity protection: duplicate semantic objects are not guessed or wrongly merged
- object version increments for meaningful object changes
- document revision increments for meaningful object or document-level changes
- compact added / updated / removed / invalidated ChangeSets
- explicit document-level changed fields such as URL, title, auth, dialogs, or security state
- bounded revision history and `changes_since(revision)`
- internal stable-object to legacy-target binding for the future semantic executor
- explicit unavailable-revision and object-not-found errors

## Document Identity

Document identity now prefers Chromium's root-frame loader identity rather than hashing the URL alone.

This means:

- `history.pushState` can change the URL without invalidating every WebObject
- a real navigation with a new loader produces a new document identity
- navigation invalidates the prior document's object set explicitly

## Frame Identity

Frame objects retain Chromium engine frame identity in internal provenance. A change in temporary `frame_1` / `frame_2` enumeration does not force a new stable object identity when the underlying engine frame remains the same.

## Version and Revision Semantics

Object versions increase when meaningful fields change, including:

- value
- selected / checked / expanded / enabled / visible state
- name, role, capability, destination, or relation changes

Ambient `busy` changes do not increment object or document revisions.

Document revisions increase for:

- added, updated, removed, or invalidated objects
- navigation or URL changes
- title/status changes
- dialog, auth, takeover, security, or structured-error changes

## Security and Correctness Boundary

- provenance remains internal and is not exposed through WebState
- raw AX/DOM/backend IDs remain unavailable to agents
- duplicate same-name objects are preserved as independent objects
- ambiguous semantic matches receive new IDs rather than unsafe identity reuse
- password values and primitive browser actions remain outside the Agent-facing model

## Compatibility

The public Runtime still returns BrowserState.

The P10 target path is now:

```text
RawWebSnapshot
  -> WebObjectCompiler
  -> ObjectRegistry
  -> stable WebState + ChangeSet
```

P10.5 will expose page/object/query/changes projections through the new observe service before changing the public MCP/REST contract.

## Validation

```text
P10.4 focused schema/compiler/registry tests: 36 passed
Real Managed Chromium identity/change test: passed
Full Python suite: 308 passed
Renderer typecheck: passed
Electron typecheck: passed
Python package build: passed
```

Validated scenarios include:

- unchanged snapshots keep IDs, versions, and revision
- backend identity survives compiler-local ID changes
- engine frame identity survives legacy frame enumeration changes
- unique semantic fallback preserves identity when strong evidence is absent
- ambiguous duplicates are never wrongly merged
- value changes increment object version and document revision
- ambient busy changes do not create revision noise
- removal, navigation invalidation, and bounded revision history
- real Chromium input and `history.pushState` behavior

## Next

P10.5 Queryable Observe:

- page projection
- object detail projection
- semantic query filtering
- changes-since projection
- result limits and range reads
- summary / standard / full / debug detail levels
- no selectors, XPath, arbitrary expressions, or raw browser evidence
