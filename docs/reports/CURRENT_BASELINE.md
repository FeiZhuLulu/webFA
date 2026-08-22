# WebFA Current Baseline

Status: current open-source Runtime baseline at `c065702`  
Date: 2026-08-22 (consolidated from P10–P12 acceptance)

This file is the single current evidence map for the kept baseline. It does not
override the current code, automated tests, public documentation, or release
checklist. An older passing report is not a release certificate for a new
artifact.

The current product line begins with the P4 Agent browser loop and converges
through P10–P12 on an agent-native internet Runtime. P1–P3 are completed
historical transaction-gateway work retained only as disabled-by-default legacy
compatibility. Profile Bootstrap remains a protected local way to provision
internet identity for an Agent. Human preview UI (Desktop Monitor, Control
Center polish, Visualizer-as-product) is not a product goal. Leftover Desktop
code is developer residue, not current direction.

The former Durable Trace / Resume phase is abandoned. Formal Windows Desktop
release is not part of this baseline.

## How to read this file

When sources disagree, use this order:

1. current implementation plus passing current tests;
2. current public contract, security boundary, and release checklist;
3. frozen P10 / P11 / P12 target designs and `docs/browser-runtime-roadmap.md`;
4. this baseline;
5. archived historical reports in the workspace `备份/` directory.

Detailed target models remain in:

- `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`
- `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`
- `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`
- `docs/ui/UI1B_MONITOR_PROJECTION_ARCHITECTURE.md`

## Phase-to-evidence matrix

| Scope | Current disposition | Live implementation | Strongest maintained evidence |
| --- | --- | --- | --- |
| P1 — transaction preview/approval/execution | Historical work complete; route abandoned as a product model and retained as legacy only | `packages/webfa-core/planner`, `approvals`, `execution`, versioned `resources/transactions` | `tests/integration/test_full_flow.py`, `test_plan_api.py`, `test_approval_api.py`, `test_execution_api.py` |
| P2 — MCP stdio foundation | Transport foundation retained; historical transaction tools require explicit opt-in | `apps/runtime/mcp/server.py`, `tools.py`, `runtime_client.py` | `tests/integration/test_mcp_stdio_browser.py`, `test_mcp_tools_flow.py`, `tests/contract/test_mcp_security_contract.py` |
| P3 — Provider connection/read context | Historical provider route retained behind the protected local control plane | `apps/runtime/api/routes/provider_connections.py`, `packages/providers`, `credential_store.py` | `tests/integration/test_provider_connection_consistency.py`, `tests/contract/test_github_no_write_contract.py` |
| P4–P9 | Completed historical milestones; public five-tool shape and Managed Chromium host evolved into the current object protocol | `apps/runtime`, `packages/webfa-core/browser` | MCP / managed-Chromium / visualizer suites |
| P10 — WebFA Object Model | Accepted and current | `packages/schemas/web.py`, `web_object_compiler.py`, `object_registry.py`, `web_observe.py`, `semantic_operations.py` | `tests/contract/test_web_object_security_contract.py`, `tests/integration/test_web_object_api.py`, `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md` |
| P11 — Agent Safety Contract | Accepted and current; Agent interprets intent, Runtime enforces deterministic mechanical boundaries | `packages/schemas/safety.py`, `safety_context.py`, `step_up.py`, `local_resource_broker.py`, `payment_broker.py` | P11 safety/resource/payment suites, `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md` |
| P12 — Multi Session / Multi Profile | Accepted and current | `profile_repository.py`, `profile_storage.py`, `session_manager.py`, `runtime_supervisor.py`, `authority_scope.py` | `tests/integration/test_profiles_api.py`, `test_multi_session_api.py`, `test_runtime_supervisor_multi_session.py`, `test_profile_storage_isolation.py`, `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md` |
| Profile Bootstrap | Reviewed and hardened; protected control-plane capability, never an Agent tool | `profile_bootstrap.py`, `profile_bundle.py`, `apps/runtime/api/routes/profiles.py` | `tests/unit/test_profile_bootstrap.py`, `test_profile_bundle.py`, `tests/integration/test_profile_bootstrap_chromium.py` |
| UI-1B Monitor and HumanControl | Accepted and maintained; projects and controls the same BrowserHost page | `visual_surface.py`, `monitor_gateway.py`, `human_control.py`, Renderer `/monitor` | Monitor / visual / human-control suites, `docs/ui/UI1B_MONITOR_PROJECTION_ARCHITECTURE.md` |
| Leftover Desktop / human preview UI | Not a product goal; leftover developer residue. Host/status/Profile/Session/approval/monitor/takeover only, with no planner, memory, model, task loop, or Agent orchestration | `apps/desktop/electron`, `apps/desktop/renderer` | Electron lifecycle/release tests, UI audit scripts, `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md` |
| Runtime source/wheel | Source/wheel developer-preview baseline is distinct from a formal signed Windows product | `pyproject.toml`, `packaging` | `tests/contract/test_python_packaging_contract.py`, `test_desktop_distribution_contract.py`, `docs/OPEN_SOURCE_READINESS.md`, `RELEASE_CHECKLIST.md` |

## P10 Object Model

The default Agent surface is an object protocol, not DOM or a global action enum:

```text
Agent -> WebState -> WebObjects -> declared capabilities -> semantic operations
      -> WebFA Runtime -> Managed Chromium BrowserHost
```

Exactly five MCP tools remain: `open_url`, `observe`, `act`, `get_tabs`,
`switch_tab`. `observe` supports `page` / `object` / `query` / `changes`.
`act` accepts only semantic operations declared by the target WebObject.

Agent-facing click, type, press, selectors, coordinates, raw DOM, Playwright,
and CDP are not part of the public contract. Managed Chromium is the only
accepted BrowserHost path. Legacy REST lives under `/v1/browser/legacy/*` and
is default-disabled.

## P11 Safety Contract

Agent interprets user intent. Runtime enforces mechanical boundaries:

```text
SafetyDeclaration -> versioned SafetyContract -> AgentAssertions
  -> Runtime evidence -> hard-boundary checks -> semantic WebOperation
  -> optional exact-scope step-up -> secret-free SafetyReceipt
```

The normal trusted-Agent path is `allow_with_audit`. Step-up is a
single-use scope escalation, not a generic approval token. Credentials,
cookies, tokens, and password values stay off the Agent surface.

Post-acceptance review closed control-plane bypasses: Visualizer mutations
require an independent control token; Desktop IPC validates the Console sender;
legacy primitive actions cannot bypass semantic safety. Remaining limits are
architectural (no anti-bot bypass, no production network isolation, no claim
that copied storage equals a live login).

## P12 Multi Profile / Multi Session

Accepted topology:

```text
one active persistent BrowserProfile
  -> one dedicated Chromium user-data-dir
  -> one dedicated ManagedChromiumHost
  -> at most one active writable BrowserSession
  -> multiple Tabs

different Profiles may run concurrently
```

`BrowserRuntimeSupervisor` owns routing and lifecycle. Page state remains
Session-local. `webfa login` uses the canonical Profile Catalog path
`profiles/default/chromium-user-data` and the Profile process lock.

Cookie, localStorage, IndexedDB, and Service Worker isolation passed on real
Chromium. CacheStorage should be rechecked if the Chromium distribution or
launch flags change.

Later closure also locked Catalog restore behind the mutation lease, rejected
link/junction redirection of Profile storage, kept live policy revocation
without creating a Session side effect, and separated the protected human
control Session from Agent grants.

## Profile Bootstrap

Protected local control plane for provisioning the durable internet identity
an Agent later uses. It is not a Chrome backup product, password vault, or
Agent-facing cookie API.

Absent from MCP, WebState, Monitor events, and SafetyReceipt. Clone/Bundle
copy Default-profile website state only; history, bookmarks, password stores,
tabs, extensions, and caches are excluded. CDP Origin is pinned to
`https://runtime.webfa.invalid`. Bundle uses streaming Scrypt + AES-256-GCM.
Restore reports browser-storage compatibility and never claims login recovery.

## UI-1B Monitor and Human Control

```text
BrowserHost owns the only real webpage instance.
Session Monitor is a projection and bounded local control surface.
Human input never becomes an Agent capability.
```

HumanControlLease is exclusive, time-bounded, and tab-scoped. Agent writes
pause while the lease is held. Release, disconnect, revoke, expiry, or Runtime
shutdown restores Runtime control and synthesizes held pointer/key releases.
The duplicate-page AuthSurface is retired.

## Freeze record

The kept commit `c065702` froze the 2026-08-02 source baseline without
changing the five-tool protocol, object model, Profile/Session authority, or
Runtime lifecycle.

Recorded gates at freeze time: Python suite 681 passed / 2 skipped; Electron
process suite 26 passed; Renderer and Electron typechecks passed; production
Renderer build passed; source UI audit 12/12; source-external wheel smoke
through installed `webfa-mcp` kept the same five tools.

`packaging/webfa-mark.svg` is the brand geometry master. This is an open-source
Runtime/source baseline, not a formal Windows release certificate.

## Honest limits

- Runtime restart interrupts active Sessions and invalidates transient
  authority. There is no durable task resume, and none is planned as a named
  phase.
- WebFA does not promise anti-bot bypass, production network isolation, or safe
  unattended high-risk account activity.
- Unknown navigation/GET side effects remain an explicit web-platform boundary.
- Human preview UI is not a product surface. Existing Desktop / Monitor /
  Visualizer code is leftover developer residue.
- A formal public Windows Desktop release is not a product goal.

## Next work

Keep the product on the Agent-native internet Runtime: real-page perception,
semantic action, and result verification. Do not spend the next phase on
human preview UI, Desktop formalization, Monitor polish, or brand. Do not
revive Durable Trace / Resume under the old phase name.
