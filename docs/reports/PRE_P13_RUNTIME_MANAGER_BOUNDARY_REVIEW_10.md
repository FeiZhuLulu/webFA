# Pre-P13 Runtime Manager Product-Boundary Review — Iteration 10

Date: 2026-07-18  
Status: phase complete; P13 Durable Trace / Resume remains deferred

## Decision

WebFA is the internet Runtime used by independent external Agents. The optional
Desktop is a lightweight local Runtime host and human management surface. It may
start and observe Runtime, expose MCP client configuration, show external
Agent/Profile/Session authority, and provide monitoring, approval, identity
management, and constrained HumanControl. It is not an Agent.

The Desktop must not acquire a model, planner, task queue, goal loop, Agent
memory, autonomous site selection, or orchestration role. External clients own
their MCP stdio connections and decide what work to perform.

## Corrections made

- Replaced ambiguous `Agent View`, `Active Agent`, and unqualified `Agent 控制`
  UI copy with `Runtime Projection`, `External Agent`, and `外部 Agent 控制`.
- Renamed the shell subtitle to `Runtime manager` and made the MCP panel state
  explicitly that Desktop neither runs nor replaces an Agent.
- Qualified waiting, failure, activity, Monitor, and control-authority copy as
  external-Agent state without changing protocol fields or runtime behavior.
- Restored source installation as the recommended README path. The Windows x64
  Runtime Manager is now an optional developer preview, not the primary product
  or a prerequisite for publishing the open-source Runtime source/wheel.
- Split future Windows signing, historical-upgrade, shell, and assistive-
  technology gates from the open-source Runtime release baseline.
- Split source/wheel verification from optional Desktop packaging commands in
  the open-source-readiness guide.
- Added a renderer contract that prevents the ambiguous embedded-Agent labels
  from returning.

## Verification

- Renderer and Electron TypeScript checks passed.
- The four focused contract files passed 32 tests after the primary correction;
  the final renderer/MCP and desktop-distribution subset passed 19 tests after
  all display-copy refinements.
- The final production Renderer build completed successfully for `/` and
  `/monitor`.
- Exact obsolete-label and whitespace scans passed.
- Real production-renderer screenshots were captured and inspected at 1440 ×
  960 and 390 × 844. `Runtime manager`, `外部 Agent 接入`, `External Agent`,
  `Runtime Projection`, and the compact projection drawer remain readable and
  unclipped.

Evidence:

- `.release/ui-audit/runtime-manager-boundary-20260718/control-center-desktop.png`
  — SHA-256 `71C2D021FBCB95294995B76CDFE36C10C781EE52DEF24D0C4768C8BBF9D8C3C0`
- `.release/ui-audit/runtime-manager-boundary-20260718/control-center-compact-projection.png`
  — SHA-256 `B69D3A2745B83BDD0E74E07B948BC90067EFDD881B7C1FC9EF7C4C2BFC9EAAAB`

No Agent permission, MCP tool, Runtime protocol, Profile authority, Session
lifecycle, or HumanControl scope changed in this iteration.

## Scope after this review

Desktop feature expansion and formal Windows distribution work are paused.
Maintenance may fix real defects and improve the existing lightweight control
surface, but the main closure line returns to the open-source Runtime, public
contracts, tests, documentation, and maintainability. P13 remains paused.
