# Pre-P13 Completion Evidence Matrix — Iteration 21

Date: 2026-07-19  
Status: phase complete; overall pre-P13 closure remains active; P13 and Desktop
expansion remain deferred

## Outcome

This review converts the repository's phase history into a current evidence
map. It does not declare every historical abstraction current, does not treat an
old report as proof for a new release candidate, and does not promote the
optional Desktop into the product's Agent layer.

The current product line begins with the P4 Agent browser loop and converges
through P10–P12 on an agent-native internet Runtime. P1–P3 are completed
historical transaction-gateway work retained only as disabled-by-default legacy
compatibility. Profile Bootstrap and UI-1B are protected local human surfaces
around the Runtime. The Desktop remains a lightweight Runtime Manager.

## Evidence authority

When sources disagree, use this order:

1. current implementation plus passing current tests;
2. current public contract, security boundary, and release checklist;
3. frozen P10/P11/P12 target designs and current roadmap;
4. final-acceptance and pre-P13 maintenance reports;
5. historical roadmaps and early phase reports.

Reports show what was exercised at a particular time. Every immutable source,
wheel, sidecar, unpacked Desktop, or installed Desktop candidate must pass its
applicable gates again.

## Phase-to-evidence matrix

| Scope | Current disposition | Live implementation entry points | Strongest maintained evidence |
| --- | --- | --- | --- |
| P1 — transaction preview/approval/execution | Historical work complete; route abandoned as a product model and retained as legacy only | `packages/webfa-core/planner`, `packages/webfa-core/approvals`, `packages/webfa-core/execution`, versioned `resources/transactions` | `tests/integration/test_full_flow.py`, `tests/integration/test_plan_api.py`, `tests/integration/test_approval_api.py`, `tests/integration/test_execution_api.py`, `docs/reports/phase1-adversarial-acceptance.md` |
| P2 — MCP stdio foundation | Transport foundation retained; historical transaction tools require explicit opt-in and are not the default Agent surface | `apps/runtime/mcp/server.py`, `apps/runtime/mcp/tools.py`, `apps/runtime/mcp/runtime_client.py` | `tests/integration/test_mcp_stdio_browser.py`, `tests/integration/test_mcp_tools_flow.py`, `tests/contract/test_mcp_security_contract.py`, `docs/reports/p2-mcp-adversarial-acceptance.md` |
| P3 — Provider connection/read context | Historical provider route retained behind the protected local control plane; it is not a site-specific Agent tool | `apps/runtime/api/routes/provider_connections.py`, `packages/providers`, `packages/storage/credential_store.py` | `tests/integration/test_provider_connection_consistency.py`, `tests/contract/test_github_no_write_contract.py`, `tests/unit/test_credential_store.py`, `docs/reports/p3-github-read-context-adversarial-acceptance.md` |
| P4/P4.5/P4.6 — first Agent browser loop and validation | Completed historical milestone; its public five-operation shape evolved into the current five-tool Web Object protocol | `apps/runtime/api/routes/browser.py`, `apps/runtime/mcp/tools.py`, `packages/webfa-core/browser/runtime.py`, `AGENT_MANUAL.md`, `AGENT_VALIDATION.md` | `tests/integration/test_browser_api.py`, `tests/integration/test_mcp_stdio_browser.py`, `tests/fixtures/agent_validation_page.html`, `docs/roadmap/stage-roadmap-and-frozen-constraints.md` |
| P5/P5.5 — Runtime Core and content blocks | Completed and superseded internally by the richer P10 object model; driver/snapshot/view boundaries remain maintained | `packages/webfa-core/browser/driver.py`, `raw_snapshot.py`, `agent_view.py`, `element_registry.py` | `tests/unit/test_raw_web_snapshot.py`, `tests/unit/test_agent_view.py`, `tests/integration/test_content_blocks.py`, `docs/reports/p5-browser-runtime-core-freeze.md` |
| P6 — managed Chromium closed loop | Completed; Managed Chromium is now the only supported BrowserHost path | `packages/webfa-core/browser/managed_chromium_host.py`, `host_driver.py`, `driver_factory.py` | `tests/integration/test_managed_chromium_driver.py`, `tests/unit/test_managed_chromium_cdp.py`, `tests/unit/test_managed_chromium_discovery.py`, `docs/reports/p6-managed-chromium-closed-loop.md` |
| P7 — generic Agent-native web operations | Completed; later formalized as P10 capability-driven semantic operations | `packages/webfa-core/browser/semantic_operations.py`, `web_capabilities.py`, `web_observe.py` | `tests/unit/test_semantic_operations.py`, `tests/integration/test_managed_chromium_driver.py`, `docs/reports/P7_ENGINEERING_FINISH_REPORT.md`, `docs/reports/P7_COMPLEX_VALIDATION_REPORT.md` |
| P8/P8.5–P8.8 — entry package, login, takeover, stability, external-Agent hardening | Completed developer-preview baseline; external Agent owns MCP identity and decisions, while humans handle secrets through protected takeover | `apps/runtime/cli.py`, `apps/runtime/login.py`, `apps/runtime/mcp/config_generator.py`, `packages/webfa-core/browser/agent_lease.py` | `tests/unit/test_cli_entrypoints.py`, `tests/unit/test_login.py`, `tests/unit/test_auth_takeover.py`, `tests/unit/test_agent_lease.py`, `tests/unit/test_mcp_config_generator.py`, `docs/reports/P8_VALIDATION_REPORT.md`, `docs/reports/P8_8_AGENT_INTEGRATION_HARDENING_REPORT.md` |
| P9/P9.2 — Runtime projection and safety hardening | Completed developer-preview baseline. P9.1 duplicate-page AuthSurface is retired and superseded by UI-1B same-page control | `apps/runtime/api/routes/visualizer.py`, `packages/webfa-core/browser/url_policy.py`, `runtime_errors.py`, `session_events.py` | `tests/integration/test_visualizer_api.py`, `tests/integration/test_p9_2_url_policy.py`, `test_p9_2_dialog.py`, `test_p9_2_frames.py`, `docs/reports/P9_2_RUNTIME_SAFETY_REPORT.md` |
| P10 — WebFA Object Model | Accepted and current | `packages/schemas/web.py`, `packages/webfa-core/browser/web_object_compiler.py`, `object_registry.py`, `web_observe.py`, `semantic_operations.py` | `tests/contract/test_web_object_security_contract.py`, `tests/integration/test_web_object_api.py`, Web Object unit suites, `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`, `docs/reports/P10_FINAL_ACCEPTANCE_REPORT.md` |
| P11 — Agent Safety Contract | Accepted and current; Agent interprets intent, Runtime enforces deterministic mechanical boundaries | `packages/schemas/safety.py`, `safety_context.py`, `safety_evidence.py`, `safety_templates.py`, `step_up.py`, `local_resource_broker.py`, `payment_broker.py`, `safety_audit.py` | P11 safety/resource/payment unit suites, `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`, `docs/reports/P11_FINAL_ACCEPTANCE_REPORT.md`, `docs/reports/P11_POST_IMPLEMENTATION_SECURITY_REVIEW.md` |
| P12 — Multi Session / Multi Profile Core | Accepted and current | `profile_repository.py`, `profile_storage.py`, `session.py`, `session_manager.py`, `runtime_supervisor.py`, `session_routing.py`, `authority_scope.py` | `tests/integration/test_profiles_api.py`, `test_multi_session_api.py`, `test_runtime_supervisor_multi_session.py`, `test_profile_storage_isolation.py`, `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`, `docs/reports/P12_8_CORE_FINAL_ACCEPTANCE_MAINTENANCE_REVIEW.md` |
| Post-Core Profile Bootstrap | Reviewed and hardened; protected control-plane capability, never an Agent tool | `packages/webfa-core/browser/profile_bootstrap.py`, `profile_bundle.py`, `apps/runtime/api/routes/profiles.py` | `tests/unit/test_profile_bootstrap.py`, `tests/unit/test_profile_bundle.py`, `tests/integration/test_profile_bootstrap_chromium.py`, `docs/reports/PROFILE_BOOTSTRAP_ADVERSARIAL_REVIEW.md` |
| UI-1B Monitor and HumanControl | Accepted and maintained; projects and controls the same BrowserHost page under a scoped lease | `visual_surface.py`, `monitor_gateway.py`, `human_control.py`, `apps/runtime/api/routes/monitor.py`, Renderer `/monitor` | Monitor/visual/human-control unit and integration suites, `docs/ui/UI1B_MONITOR_PROJECTION_ARCHITECTURE.md`, `docs/reports/UI1B_PHASE_6_MAINTENANCE_REVIEW.md` |
| Lightweight Desktop Runtime Manager | Optional developer preview; host/status/Profile/Session/approval/monitor/takeover only, with no planner, memory, model, task loop, or Agent orchestration | `apps/desktop/electron`, `apps/desktop/renderer`, `apps/runtime/api/visualizer_control.py` | Electron lifecycle/release tests, Renderer/control contracts, source/installed UI audit scripts, `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md`, pre-P13 reviews 2–10 and 16–20 |
| Runtime source/wheel and optional Windows distribution | Source/wheel developer-preview baseline is distinct from a formal signed Windows product | `pyproject.toml`, `packaging`, `scripts/build-sidecar.ps1`, release/package verification scripts | `tests/contract/test_python_packaging_contract.py`, `tests/contract/test_desktop_distribution_contract.py`, `docs/OPEN_SOURCE_READINESS.md`, `RELEASE_CHECKLIST.md`, pre-P13 reviews 5, 6, 8, and 11 |

## Cross-cutting closure evidence

Pre-P13 iterations 1–20 cover documentation truth, Monitor authority, UI
hierarchy, lifecycle/process cleanup, Python packaging, installed-candidate
verification, failure/recovery UX, keyboard/focus/responsive behavior, the
Runtime Manager product boundary, open-source distribution, SQLite concurrency
and migration integrity, connection/Session lease authority, initialization and
lifespan ownership, MCP client state, protected control authentication, and
empty-state visual balance. The reports index explains how to read these
point-in-time results.

The maintained regression surface is the full Python suite, Electron process and
release suite, Renderer/Electron type checks, production Renderer build, and
source UI audit. Candidate-specific frozen sidecar, unpacked, installed,
upgrade, and signing gates remain governed by `RELEASE_CHECKLIST.md`.

## Honest limits and deferred work

- P13 Durable Trace / Resume is not implemented. Runtime restart interrupts
  active Sessions and invalidates transient authority.
- P12's accepted real-Chromium isolation evidence carries a documented
  CacheStorage verification note. Cookie, localStorage, IndexedDB, and Service
  Worker isolation passed; CacheStorage should be rechecked if the Chromium
  distribution or launch flags change.
- WebFA does not promise anti-bot bypass, production network isolation, or safe
  unattended high-risk account activity. Unknown navigation/GET side effects
  remain an explicit web-platform boundary.
- Current Desktop audits are strong developer-preview evidence, not a complete
  WCAG or real-assistive-technology acceptance claim.
- A formal public Windows release still requires the unchecked identity,
  upgrade, clean-user, installed-shell, accessibility, signing, timestamp, and
  exact-candidate rerun gates in `RELEASE_CHECKLIST.md`. Those Desktop-only gates
  do not redefine the open-source Runtime.

## Documentation corrections

- Added `docs/reports/README.md` so historical reports cannot be mistaken for
  current product truth or independent release certificates.
- Added this matrix as the single current phase-to-implementation-to-test map.
- Linked the matrix from both public READMEs.
- Added a documentation contract that verifies the matrix's referenced files,
  legacy/current phase distinction, P13 deferral, and lightweight Desktop
  boundary.

## Verification

- Full Python suite: 656 passed, 2 skipped.
- Electron process/release suite: 26 passed.
- Renderer TypeScript: passed.
- Electron TypeScript: passed.
- Next production Renderer build: passed.
- Source UI audit: passed, 8 captures; no horizontal overflow, escaped controls,
  unnamed visible buttons, or unlabeled visible fields; compact drawers remained
  opaque modal surfaces with two inert background regions, and visible empty
  states had zero-pixel center offset.
- Documentation evidence contract: passed.
- `git diff --check`: passed for the iteration files.

The two skipped Python tests are environment-specific: POSIX permission bits do
not represent Windows ACLs, and symbolic links are unavailable in the current
test environment. Their reasons were reviewed with `pytest -rs`. No failure was
hidden or converted into a skip by this iteration.
