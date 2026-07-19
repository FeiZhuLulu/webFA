# Pre-P13 Closure and UI Review — Iteration 1

Date: 2026-07-16

## Scope

This iteration starts the pre-P13 closure program. P13 Durable Trace / Resume is explicitly deferred. The reviewed surface covered current documentation, the five-tool public MCP contract, release/build gates, LocalResourceBroker lifecycle cleanup, and the human-facing Control Center. The Session Monitor received a visual baseline inspection but no implementation change in this iteration.

## Findings and corrections

### 1. Current documentation contradicted accepted P12 behavior

The Chinese and English READMEs still claimed that agents shared one default Profile and that multi-Profile / multi-Session isolation was not implemented. They now describe connection-scoped Profile Grants, exclusive writable Sessions per Profile, concurrent operation across different Profiles, and the actual restart boundary. The roadmap and both READMEs now record that P13 is deferred during closure and UI maintenance.

### 2. Windows process liveness probing could delete an active local resource Session

`LocalResourceBroker` used the POSIX `os.kill(pid, 0)` liveness idiom on Windows. A second Broker could therefore classify an active Session directory as orphaned and delete its authorized backing file. Windows now uses a non-mutating `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` plus `GetExitCodeProcess` check. Access-denied probes fail closed and preserve the directory. POSIX retains signal-zero probing. Regression coverage now distinguishes the current process, a live external process, and an exited process.

### 3. Control Center information architecture no longer fit the implemented product

Runtime controls, Profile Bootstrap, local resources, and Safety Center had accumulated in one 260-pixel column with several nested scroll areas. The Control Center now provides persistent Overview, Identity, and Safety workspaces inside one scroll container. The first visual upgrade also adds a coherent warm-neutral palette, a single teal accent, unified inputs and buttons, visible keyboard focus, reduced-motion support, a clearer empty preview state, accessible collapsed sidebars, and responsive 288 / 384 / 288 column sizing at the Electron minimum 960-pixel window width. Automatic offline polling no longer produces repeated raw error toasts.

## Verification evidence

- Local visual inspection: Control Center at the default browser viewport and 960 × 640; Overview, Identity, Safety, collapse/restore, empty state, single-scroll behavior, and horizontal overflow checked.
- Session Monitor: current empty/error state captured as the visual baseline for the next UI iteration.
- Renderer TypeScript: passed.
- Electron TypeScript and build: passed.
- Next production build: passed; `/`, `/_not-found`, and `/monitor` prerendered.
- Python: 521 passed, 1 skipped, 2 existing upstream deprecation warnings.
- Focused LocalResourceBroker regression: 8 passed.
- Python sdist and wheel: passed.
- `git diff --check`: passed.
- Public MCP surface remains exactly `open_url`, `observe`, `act`, `get_tabs`, and `switch_tab`; the full contract suite is included in the passing Python baseline.

## Remaining work

- Continue the maintenance and adversarial audit across lifecycle, authority, migration, packaging, and historical compatibility boundaries.
- Perform the next UI iteration on Session Monitor hierarchy, empty/error states, responsive behavior, and interaction feedback.
- Reduce remaining inline presentation styles in large protected-control components while preserving their security-sensitive flows.
- Keep P13 implementation out of scope until this closure program reaches a proven release baseline.
