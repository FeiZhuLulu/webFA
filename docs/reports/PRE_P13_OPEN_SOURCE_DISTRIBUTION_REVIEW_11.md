# Pre-P13 Open-Source Runtime Distribution Review — Iteration 11

Date: 2026-07-18  
Status: phase complete; P13 Durable Trace / Resume and Desktop expansion remain deferred

## Outcome

The open-source Python Runtime now has a reviewed wheel/sdist path that preserves
the product boundary: independent external Agents own their decisions and MCP
connections; WebFA supplies the internet Runtime; the optional Desktop remains a
lightweight host and human management surface.

The historical distribution identifier `webfa-desktop-runtime` is retained for
compatibility with existing tags, sidecar manifests, CLI consumers, and upgrade
checks. Package summary, public URLs, CLI copy, README, and integration guides
now describe the installed product as an internet Runtime for external Agents.
Any future package rename requires an explicit migration rather than a silent
closure change.

## Corrections made

- Changed generated default identity from the ambiguous shared `webfa-agent` to
  `external-agent`; CLI and Desktop copy now tell every client to set a distinct
  stable `WEBFA_AGENT_ID`.
- Removed `WEBFA_BROWSER_DRIVER` and `WEBFA_AUTH_TAKEOVER` from Codex, Claude
  Code, Kimi Code, and OpenCode client configs. Those are Runtime-host policies,
  not authority delegated to an external Agent configuration.
- Updated all four guides for optional `profile_ref`, one writable Session per
  persistent Profile, concurrent Sessions on different Profiles, and
  `session_busy` / legacy `agent_busy` handling.
- Separated recommended Python source installation from optional Visualizer Node
  dependencies and made README language links valid outside a repository checkout.
- Added repository/Homepage/Issues package metadata and distribution contracts
  for public entry points, external-Agent positioning, client/host separation,
  and source-only installation.
- Found that `webfa doctor` still called disabled P7 BrowserAction endpoints.
  Replaced that loop with the supported Web Object path: open, full observe,
  semantic `set_value`, semantic `submit`, and query observe. A real installed
  wheel exposed the defect; a rebuilt wheel verified the correction.

## Final artifacts

Directory: `.release/source-dist/iteration-11-release`

- `webfa_desktop_runtime-0.2.0-py3-none-any.whl` — 276,065 bytes — SHA-256
  `6487E294797E018891F0934FD59C4B27A8553B3CE90FC4DFA4A1C93CC53BAC54`
- `webfa_desktop_runtime-0.2.0.tar.gz` — 236,541 bytes — SHA-256
  `8917D6BB9F433DD5E15C25DA05E9A9C6497BB2F448AD5EC7A1AFF7932D3DDACA`

The wheel contains 160 entries and the sdist 195. Neither contains tests,
Desktop source, `.git`, `.progress`, `.env`, `node_modules`, or release/build
trees. The wheel contains the five expected YAML resources and exactly the
`webfa`, `webfa-runtime`, and `webfa-mcp` console entry points.

## Verification

- Focused CLI, Runtime-client, packaging-contract, lifecycle, and real MCP
  browser tests: 56 passed; the final doctor/MCP subset: 22 passed.
- Renderer TypeScript check and optimized production build passed for `/` and
  `/monitor`. The only UI change in this iteration is clearer external-client
  identity guidance; no new Desktop feature, panel, or orchestration behavior
  was added.
- Source-mode `webfa doctor` passed against a fresh local Runtime and Chrome.
- The rebuilt wheel was installed outside the repository. Its distribution and
  import locations resolved to the verification venv, packaged resources were
  present, `pip check` reported no broken requirements, all three CLI entry
  points worked, and the default MCP config emitted `external-agent`.
- Installed-wheel `webfa doctor` passed Runtime health, Managed Chromium
  selection, browser discovery, exact five-tool surface, and the Web Object
  action loop.
- Installed `webfa-mcp.exe` independently auto-started Runtime and completed
  `initialize -> tools/list -> open -> observe -> act -> observe`; the exact tool
  set was `webfa.open_url`, `webfa.observe`, `webfa.act`, `webfa.get_tabs`, and
  `webfa.switch_tab`.

A completely empty venv dependency install was also attempted. Resolution and
all cached packages succeeded, but the current network path repeatedly stalled
while downloading the official 6.9 MB `pywin32` wheel. The final functional
verification therefore used a source-invisible venv with the already installed
dependency set plus the candidate wheel. This external download limitation is
recorded rather than misreported as a full online-install success; no WebFA
dependency conflict or package-content failure was observed.

## Scope after this review

The Runtime source/wheel baseline is substantially cleaner, but the overall
pre-P13 goal remains active for further maintenance and adversarial review.
Desktop work stays limited to defects, clarity, accessibility, and visual polish
on the existing Runtime Manager surface. It must not gain a model, planner, task
loop, Agent memory, or orchestration role. P13 remains paused.
