# Pre-P13 Python Distribution Review — Iteration 5

Date: 2026-07-16

> **Historical iteration snapshot.** This report preserves the state and
> remaining-work assessment at the end of iteration 5. Its statements that the
> Electron path was development-only and that no Desktop packaging target
> existed have since been superseded by
> `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md` and `RELEASE_CHECKLIST.md`. The
> current repository has a formal onedir/unpacked/NSIS build model, automated
> installed lifecycle coverage, and real installed UI/external-MCP evidence.
> Stable `appId`, a true upgrade from a real prior supported installer, clean
> Windows shell/standard-user acceptance, the remaining HumanControl/failure
> states, and production signing remain open release gates.

## Scope

P13 Durable Trace / Resume remains deferred. This iteration audited the Python sdist/wheel as an installed product rather than importing from the repository. It covered packaged resources, console entry points, non-default address binding, installed Runtime startup, transaction capability preservation, and shutdown. Desktop installer architecture is recorded separately as remaining work because the current Electron scripts are still source/development launch paths.

## Findings and corrections

### 1. The wheel silently discarded WebFA's versioned resource definitions

The distribution contained Python modules but not `resources/`. An installed Runtime therefore started successfully with an empty transaction registry: GitHub, Hugging Face, and mock transaction definitions all disappeared without an error. The resources are now explicit `webfa_resources` packages with declared YAML package data, shared by source and installed resolution.

### 2. Missing or empty transaction resources failed open

`build_default_registry()` previously treated a missing directory as an ordinary empty registry. That made corrupt or incomplete installations indistinguishable from a valid capability set. The registry now fails startup with a bounded `RuntimeError` when the transaction directory is absent or contains no definitions.

### 3. Runtime resource discovery depended on repository layout

`apps.runtime.main` computed `../../resources` from its source file. After wheel installation that resolved outside `site-packages` and could never find package data. Runtime startup now uses the registry's shared source-or-package resolver while preserving `WEBFA_RESOURCES_ROOT` as an explicit override.

### 4. Non-default CLI binding produced incorrect Runtime identity

`webfa-runtime --port 8797` listened on 8797 but `/health` reported 8787 because the CLI did not propagate its selected host and port into Runtime state. The same mismatch existed when `ensure_runtime()` auto-started a non-default URL. Both launch paths now set `WEBFA_API_HOST` and `WEBFA_API_PORT` in the child/runtime environment, with regression coverage.

### 5. The first resource package declaration was buildable but ambiguous

Setuptools initially warned that YAML directories looked like undeclared namespace packages. They are now explicit resource subpackages with scoped package-data declarations. The final sdist and wheel build completes without that ambiguity and includes all policy, blocked-path, and transaction YAML files.

## Verification evidence

- Packaging and entry-point focused tests: 20 passed.
- Python sdist and wheel: passed from isolated PEP 517 build environments.
- Source-isolated wheel verification used a separate venv, cleared `PYTHONPATH` and `WEBFA_RESOURCES_ROOT`, and ran from a directory outside the source import path.
- Installed `apps.runtime.main` resolved from the venv's `site-packages`, not the repository.
- Installed registry loaded exactly `github.patch_and_open_pr`, `hf.compare_and_publish`, and `mock.patch_and_open_pr` from `site-packages/webfa_resources`.
- Installed `webfa-runtime` started on 127.0.0.1:8797, `/health` reported the same URL, `/v1/transactions` returned all three definitions, and the process exited cleanly.
- Electron TypeScript check: passed.
- Full Python suite: 535 passed, 1 skipped, with 2 existing upstream `websockets` deprecation warnings.
- `git diff --check`: passed; only existing LF-to-CRLF checkout notices were emitted.

## Remaining work

- Define and implement one production desktop distribution contract: renderer asset serving, packaged Runtime/MCP ownership, Python/runtime sidecar strategy, Chromium discovery, app data paths, and installer contents must be coherent rather than inferred from development paths.
- Add an actual Electron packaging target and exercise an unpacked/installed app start-stop cycle only after that contract is fixed.
- Review MCP entry-package behavior from the installed wheel with a real external MCP client process.
- Continue UI refinement against real packaged/offline/startup-failure states.
- Keep P13 implementation out of scope until the current release baseline is proven.
