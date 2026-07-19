# Pre-P13 Public Protocol and Control Boundary Review — Iteration 18

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop expansion remain deferred

## Outcome

This iteration reconciled the executable REST/OpenAPI, MCP, CLI, documentation,
and built Python distribution surfaces. It corrected human-control authorization
gaps without adding a planner, task loop, memory, orchestration, or other Agent
responsibility to Desktop. WebFA remains the internet Runtime used by independent
external Agents; Desktop remains an optional lightweight Runtime Manager.

## Defects reproduced

### 1. Protected operations appeared anonymous in OpenAPI

The existing control dependency read `X-WebFA-Visualizer-Token` manually from a
FastAPI `Request`. Runtime behavior rejected unauthorized calls, but OpenAPI
contained neither an API-key security scheme nor per-operation security
requirements. Generated clients and human reviewers therefore received a false
public contract.

### 2. Credential controls and human approval decisions were bare loopback REST

The historical GitHub Provider connection routes allowed any local HTTP caller
to read connection metadata, store/test a PAT, or disconnect the account. The
historical `approve` and `reject` routes likewise allowed an Agent-capable local
caller to make the human decision that gates its own legacy transaction flow.
Loopback transport is not authorization, and the later P11 threat model already
treats local Agent processes as untrusted relative to the human control plane.

### 3. Retired compatibility operations looked current

The default-disabled primitive Browser API and permanently retired duplicate-
page AuthSurface routes remained visible in OpenAPI without `deprecated: true`.
They were explicitly named legacy, but generated clients still presented them
as peers of the supported Agent-native Web operations.

## Corrected public boundary

The existing process-local token is now represented by the OpenAPI
`VisualizerControlToken` API-key scheme. The historical environment/header
names remain stable:

```text
WEBFA_VISUALIZER_CONTROL_TOKEN
X-WebFA-Visualizer-Token
```

The dependency uses FastAPI `Security(APIKeyHeader(..., auto_error=False))` so
the schema is accurate while the established fail-closed behavior remains:

- missing Runtime configuration: `503 visualizer_control_unavailable`;
- missing or incorrect request token: `403 visualizer_control_forbidden`;
- the raw token is never serialized in a response.

The resulting authority split is:

| Surface | Control-token requirement |
| --- | --- |
| `/v1/browser/web/*`, default five MCP tools, health | no human token; Agent Runtime surface |
| `GET /v1/approvals` and `GET /v1/approvals/{id}` | no human token; Agent may poll approval state |
| `POST .../approve` and `POST .../reject` | required; human decision |
| `/v1/providers` | no human token; redacted Agent discovery |
| `/v1/providers/github` connection status/connect/test/disconnect | required; credential administration |
| `/v1/visualizer/*`, `/v1/profiles*`, `/v1/profile-bundles/*` | required; local human control and identity administration |

No control token was added to MCP configuration, Agent headers, WebState,
Monitor grants, prompts, or Agent-facing operation schemas.

## Compatibility metadata and documentation

The four `/v1/browser/legacy/*` operations and the three retired AuthSurface
aliases are now marked deprecated in OpenAPI. They retain their prior explicit
compatibility behavior; the unsafe Browser API still requires its opt-in switch,
and retired AuthSurface calls still return `410`.

README and GitHub credential-handling guidance now describe the broader local
human-control boundary and required header. Historical live adversarial scripts
also supply the configured control token for approval and Provider operations.

This intentionally hardens an old pre-release loopback contract: standalone
human-control clients must now configure and send the token. Default external
Agent MCP clients and the five Agent-native tools are unchanged.

## Installed-distribution protocol audit

A fresh source build produced the `0.2.0` sdist and wheel under
`.release/python-dist/iteration-18-20260719`. The wheel contained 159 files,
included the corrected control/route modules, and excluded the deleted
`apps/runtime/api/auth_surface_session.py` module.

The wheel was force-installed without source-tree imports into the dedicated
`.release/protocol-audit/iteration-18-venv` environment and verified from its
`site-packages` copy:

- `webfa --version`: `0.2.0`;
- OpenAPI info version: `0.2.0`;
- OpenAPI paths: 73;
- the human-control API-key scheme and operation security were present;
- approval reads remained public while approval decisions were protected;
- Provider credential status was protected;
- legacy Browser operations were deprecated;
- generated MCP configuration contained only Runtime URL and Agent ID, with no
  human-control token; and
- default MCP tools remained exactly `open_url`, `observe`, `act`, `get_tabs`,
  and `switch_tab`.

## Regression

- Python: 639 passed, 1 skipped; two third-party websocket deprecation warnings.
- Targeted control/protocol flow: 24 passed.
- Electron process/release suite: 26 passed.
- Electron TypeScript check: passed.
- Renderer TypeScript check: passed.
- Electron production build: passed.
- Renderer production build: passed for `/`, `/_not-found`, `/icon.png`, and
  `/monitor`.
- Python sdist/wheel build: passed.
- Installed-wheel CLI/OpenAPI/MCP audit: passed.
- `compileall` and `git diff --check`: passed apart from repository-wide Windows
  line-ending notices.

No Renderer or Electron product behavior changed in this iteration, so the
accepted responsive visual evidence remains iteration 17. Rebuilding the
Renderer verified integration without expanding or visually redesigning the
Desktop surface.

## Remaining boundary

This phase does not claim that Agent identity is a cryptographic network
principal. Runtime/MCP remains a loopback/local deployment contract and must not
be exposed directly to an untrusted network. P13 Durable Trace / Resume remains
deferred. Desktop expansion remains deferred, and the overall pre-P13 closure
goal remains active for further maintenance and adversarial review.
