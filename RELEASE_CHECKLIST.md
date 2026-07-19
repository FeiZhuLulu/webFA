# WebFA Release Checklist

Use this checklist for WebFA Runtime source/wheel candidates and, separately,
for the optional Windows Runtime Manager preview. It covers P1-P12, Post-Core
Profile Bootstrap, and the existing lightweight Desktop control plane. P13
Durable Trace / Resume is explicitly deferred and must not be implied by any
release claim.

Checkboxes in **Implemented baseline** describe repository capabilities that
already exist. Candidate gates apply only to the artifact being published: an
unchecked Windows installer/signing gate does not block a Runtime source or
wheel release. A build script or an older passing artifact is not evidence that
a new candidate passed.

## Release status

- [x] P10 WebFA Object Model, P11 Agent Safety Contract, P12 Multi Session /
  Multi Profile Core, and Post-Core Profile Bootstrap are implemented.
- [x] The product remains an agent-native internet Runtime; Desktop is an
  optional local Runtime host and human management surface, not a browser and
  not an Agent. External Agent clients own their MCP connections and decide
  what work to perform.
- [x] Multiple persistent Profiles can run concurrently, while one persistent
  Profile has at most one active writable Session and one exclusive Agent
  Session lease.
- [x] Runtime restart preserves Profile browser storage but invalidates active
  Sessions, Profile/Monitor grants, leases, Step-up state, and other in-memory
  authority. Stale active Session records become `interrupted`.
- [x] P13 Durable Trace / Resume is deferred; no release material promises task
  replay, page restoration, or resumable execution.
- [ ] Before a formal Windows Desktop release only, close its distribution
  blockers: stable public `appId`, true
  upgrade from a real previous supported installer, clean standard-user and
  installed-shell validation, remaining keyboard and real
  assistive-technology acceptance, and signed and timestamped binaries with
  every installed gate repeated.

The current repository can produce a Windows developer preview. It is not a
formal public Windows release until every unchecked Desktop candidate gate
below is complete; those gates do not redefine or delay the open-source Runtime
release baseline.

## Implemented baseline

### Agent and authority contracts

- [x] The default MCP tool list is exactly `webfa.open_url`,
  `webfa.observe`, `webfa.act`, `webfa.get_tabs`, and `webfa.switch_tab`.
- [x] Legacy transaction tools require `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
- [x] BrowserState/BrowserAction compatibility is isolated under
  `/v1/browser/legacy/*`, omitted from OpenAPI, unused by MCP, and disabled
  unless `WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1` is deliberately set.
- [x] Agent-visible schemas contain no raw Playwright/CDP handles, selectors,
  XPath, evaluate escape hatch, browser-storage values, credentials, tokens,
  local paths, or full DOM/HTML.
- [x] `profile_ref` is an opaque Profile reference. Profile CRUD, policy
  mutation, human login, Cookie import, clone, and Bundle operations remain in
  the separately token-protected local control plane.
- [x] Versioned Profile policy metadata may be narrowed while a Session exists
  and continued Agent activity rechecks it. This live Catalog update is distinct
  from Cookie/Bundle/clone/deletion storage maintenance, which remains offline
  behind `ProfileMutationLease`; a Session never switches to another Profile.
- [x] Protected control-plane Session management does not impersonate an Agent
  or mint an Agent Profile Grant or Session write lease. Empty safety/resource
  reads do not create a Session, while an explicit Session-scoped mutation may
  create a management Session without webpage authority.
- [x] Profile archive and soft-restore hold the OS-backed mutation lease before
  changing Catalog state. Profile identifiers reject path/drive syntax, and the
  managed Profile root plus direct user-data/download/maintenance directories
  reject symbolic links and directory junctions.
- [x] Agent Profile Grants are connection-scoped and expiring; Agent Session
  Leases bind Agent, connection, Profile, Session, runtime generation, and
  expiry. A second connection cannot write the same active Profile Session.
- [x] Tab/WebObject routes, Monitor grants, HumanControlLease, SafetyContext,
  exact-scope Step-up, LocalResourceGrant, payment state, and SafetyReceipt are
  bound to their required Profile/Session/connection/generation scopes.
- [x] Session Monitor projects the same BrowserHost page. A time-bounded,
  Session-scoped HumanControlLease forwards local input only to that page; the
  retired duplicate-page Electron AuthSurface is not a supported control path.
- [x] Step-up grants bind the exact navigation fingerprint or document/object/
  operation/scope, are single-use by default, and do not expose human notes.
- [x] Protected file input accepts an opaque, scoped `resource_ref`; arbitrary
  local paths do not enter Agent-visible requests, responses, logs, or receipts.
- [x] Payment instrument references contain safe display metadata only; final
  payment commit rechecks the active document, selected instrument, amount,
  currency, policy limits, and usage accounting.

### Runtime and sidecar distribution

- [x] Python wheel/sdist package the required policy, blocked-path, and
  transaction resources and fail closed when the transaction registry is
  absent or empty.
- [x] `webfa`, `webfa-runtime`, and `webfa-mcp` delegate to the same multi-call
  command implementation used by the frozen sidecar.
- [x] The Windows sidecar build uses a pinned Windows x64 CPython 3.12 and
  PyInstaller toolchain, builds a wheel first, freezes from that installed
  wheel, and stages a source-free **onedir** bundle for Electron packaging.
- [x] Every third-party Windows sidecar wheel is exact-versioned and SHA-256
  pinned in `packaging/python-windows-release-lock.txt`; installation uses
  `--only-binary=:all: --require-hashes`. The current WebFA wheel is built from
  the candidate source and installed separately with `--no-deps`.
- [x] Sidecar smoke runs outside the repository with a sanitized environment,
  verifies exact product/release/protocol/instance identity, all packaged
  transaction definitions, and the exact five-tool MCP surface.
- [x] Sidecar smoke launches the real frozen MCP stdio entry and proves that an
  MCP client exiting does not terminate an external Runtime.
- [x] MCP Runtime auto-start is loopback-only, identity-checked, cross-process
  locked, client-leased, and stops only the Runtime instance it owns.

### Desktop distribution and process ownership

- [x] Production Renderer assets are a static export served by an
  Electron-owned loopback HTTP server; packaged mode does not use a development
  server or `file://`.
- [x] Electron accepts only an exact compatible Runtime identity and never
  adopts or terminates an external Runtime occupying the configured endpoint.
- [x] Electron generates a high-entropy control token for each owned Runtime
  start, rotates it on restart, exposes it only to validated local Renderer IPC,
  and clears it when ownership ends.
- [x] Desktop owns the Runtime child it starts. The Agent client owns its MCP
  stdio bridge. Runtime owns Session workers and BrowserHost descendants.
- [x] Desktop shutdown waits for owned process-tree termination; stale child
  events cannot overwrite a replacement process, and external Runtime/MCP
  processes are not killed.
- [x] Release inputs pin the exact Electron Windows archive checksum and a
  packaged Windows toolchain lock for Electron Builder, NSIS, NSIS resources,
  and 7-Zip; they reject version drift, symlinks, source/maps, an obsolete
  desktop MCP process, and an unverified sidecar.
- [x] The Windows packaging entry enforces the exact Node/npm engine versions,
  performs a fresh `npm ci --ignore-scripts` followed by `npm audit`, sanitizes
  inherited build/control variables, and then builds the release inputs.
- [x] Unsigned and signed electron-builder YAML files are parsed as structured
  data and compared with the complete expected effective configuration; textual
  fragments cannot satisfy this gate.
- [x] The generated build manifest binds the package, Python, and Windows
  toolchain lock hashes, Electron archive, application icon, audited NSIS hook,
  complete sidecar bundle and Authenticode-invariant PE payload, and canonical
  Desktop ASAR input set.
- [x] Electron packaging verifies the exact ASAR file set, byte-compares every
  compiled Electron/Renderer asset with its release input, checks the exact
  reduced application manifest, and rejects source, maps, `node_modules`, and
  obsolete process modules. Every unchanged Electron runtime and legal file is
  byte-bound to the pinned archive, and the complete unpacked file set rejects
  additions. The packaged ASAR and sidecar payload are rebound to the packaged
  build manifest after electron-builder runs.
- [x] Packaged Desktop forces the bundled Runtime's `WEBFA_HOME` to Electron
  `app.getPath("userData")`; an inherited parent `WEBFA_HOME` cannot redirect
  packaged Profile/Session data or cause writes beneath program files.
- [x] The WebFA icon is validated as a multi-resolution Windows ICO, copied as
  an application resource, embedded into the Desktop and sidecar executables, and
  selected for BrowserWindow, Monitor, Tray, installer, and uninstaller use.
- [x] A packaged-only unpacked lifecycle smoke verifies the Renderer shell,
  exact Runtime identity and Desktop ownership, direct `/health`, application
  icon loading, hostile inherited-`WEBFA_HOME` isolation, bounded quit, closed
  Runtime port, stopped Renderer server, and absence of packaged Desktop/sidecar
  processes after exit.
- [x] Hardened Electron fuses disable RunAsNode, NODE_OPTIONS, CLI inspect, and
  extra file-protocol privileges; enable cookie encryption and embedded ASAR
  integrity; and restrict loading to ASAR.
- [x] The Windows NSIS configuration is x64, per-user, `asInvoker`, and does not
  request elevation; automatic publish/update metadata, differential packages,
  and the unused elevation helper are disabled.
- [x] The installer verifier checks exact Windows version identity and icons,
  the PE and NSIS physical envelope, strict Authenticode certificate-table
  structure when present, the embedded 7z physical range/integrity, and a full
  file/hash match between the installer payload and `win-unpacked`.
- [x] The NSIS hook fails before extraction when the Windows temporary volume
  has less than 4 GiB free, removes only the cached release installer during
  uninstall, and leaves `%APPDATA%\WebFA` Profile data outside its deletion
  scope. The hook itself is hash-bound to the packaged build manifest.
- [x] The installed-artifact smoke performs a real current-user install into an
  owned directory, byte-compares all 223 release files, validates the two
  install-time files, registry identity, shortcuts, updater cache, and
  Authenticode mode, launches the installed Desktop lifecycle twice across a
  same-version reinstall, and then proves uninstall removed program files,
  registry keys, shortcuts, updater cache, and processes.
- [x] The installed UI audit performs a real install of the exact candidate,
  captures Control Center and Session Monitor at desktop and 390px compact
  layouts, records DOM and accessibility-tree evidence, validates drawer focus
  restoration, overflow/label invariants, the absence of raw fetch errors or
  lingering error toasts, then closes and uninstalls cleanly.
- [x] The installed UI audit drives the critical path by keyboard: both skip
  links, compact drawer focus loops and Escape restoration, desktop and mobile
  HumanControl acquisition, Escape from page capture to a visible local control,
  capture re-entry, Agent return, and all five failure-recovery actions. An
  active HumanControl lease can always be returned while connected even when a
  visual frame is temporarily unavailable.
- [x] Compact Monitor drawers remain mutually exclusive, while desktop sidebars
  are independent. Leaving compact layout restores the user's prior desktop
  sidebar state and the installed audit proves both default sidebars return.
- [x] That audit launches a real external MCP client from the Runtime-advertised
  installed sidecar configuration, proves the exact five-tool JSON-RPC flow,
  preserves Desktop Runtime ownership, and captures both Control Center state
  and the live Monitor frame for the same Agent/Profile/Session.
- [x] The installed UI audit also captures the startup boundary, graceful
  Runtime stop, Monitor disconnect with stale projection removed, incompatible
  endpoint collision, recovery after endpoint release, and missing Chromium at
  desktop and 390px by isolating every supported browser discovery root. Each
  captured step fails on horizontal overflow, viewport escapes, unnamed visible
  buttons/fields, an empty accessibility tree, visible error toasts, or raw
  network failure text.
- [x] The audit can isolate the exact hash-bound installed sidecar outside the
  install tree, prove missing and corrupt executable handling, inject a valid
  audit-owned process that never supplies health identity, confirm the real
  20-second startup timeout reaps its owned process, restore the original
  sidecar by exact SHA-256, and prove successful restart. This is external
  harness mutation only; no product failure-injection switch is shipped.
- [x] `scripts/smoke-upgrade-desktop.cjs` defines the real cross-version gate:
  it rejects same/newer versions and `appId` changes, verifies historical
  signer identity and the packaged default user-data name, runs both installed
  versions against one owned persistent user-data tree, performs the in-place
  upgrade, rejects stale files, and proves an exact Profile sentinel survives
  upgraded Runtime startup and uninstall before removing only test-owned state.
  The gate is not passed until a real prior supported installer is supplied and
  the command succeeds.

## Candidate gates

### Source and contract verification

- [ ] Working tree and submodules contain only the intended release changes;
  generated databases, virtualenvs, caches, logs, screenshots, secrets, and
  `.release/` artifacts are not committed.
- [ ] Public docs contain no personal paths, account names, credentials,
  private screenshots, or generated clipboard material.
- [ ] The exact Node/npm toolchain completes a fresh lockfile install and audit
  for this candidate. The packaging entry performs these checks automatically;
  rerunning an older populated `node_modules` tree is not sufficient evidence.
- [ ] All Python tests pass from a clean environment:

  ```powershell
  python -m pytest -q
  ```

- [ ] Electron process/server tests and both TypeScript checks pass:

  ```powershell
  npm run test:electron-process
  npm run typecheck:electron
  npm run typecheck:renderer
  ```

- [ ] Python sdist and wheel build successfully and an installed-wheel smoke
  runs outside the repository with cleared source import paths:

  ```powershell
  python -m build
  ```

- [ ] Renderer production export and Electron compilation complete without
  development-only fallback:

  ```powershell
  npm run build:renderer
  npm run build:electron
  ```

### Frozen sidecar and MCP

- [ ] Build the exact **onedir** sidecar used by Electron, then rerun its smoke:

  ```powershell
  npm run build:sidecar:onedir
  npm run verify:sidecar
  ```

- [ ] `npm run verify:release-inputs` passes for the staged Renderer, Electron
  code, Electron archive, icon, sidecar bundle, structured builder
  configurations, dependency locks, build manifest, SBOM, and notices.
- [ ] A real external MCP client completes JSON-RPC `initialize`, `tools/list`,
  and a five-tool workflow (`open_url -> observe -> act -> observe`) against the
  frozen sidecar, not repository Python or a mocked transport.
- [ ] Closing one MCP client leaves an external/Desktop-owned Runtime alive;
  closing the last client reaps only an MCP-auto-started Runtime and all of its
  descendants.

### Electron unpacked artifact

- [ ] `npm run package:unpacked` succeeds from clean release inputs. The command
  must complete its built-in `verify:unpacked` and packaged lifecycle smoke
  against that exact unpacked artifact; neither step may be skipped.
- [ ] The packaged app starts with source Python, global Python, development
  Renderer servers, and repository paths unavailable.
- [ ] Runtime identity/version and bundled sidecar contents match the Desktop
  version; build-manifest bindings for ASAR and sidecar payload, Electron
  checksum, hardened fuses, icon embedding, `WEBFA_HOME` isolation, and token
  boundary are reverified from the final executable.
- [ ] Port collision, incompatible external Runtime, missing/corrupt sidecar,
  missing Chromium, and Runtime startup failure each produce a bounded,
  actionable UI state without gaining control authority.
- [ ] A hostile Renderer navigation/IPC attempt and static-server traversal
  attempt fail closed.
- [ ] Start, stop, restart, rapid restart, Desktop close, and OS shutdown paths
  leave no owned Runtime, BrowserHost, Renderer server, or descendant process.

### UI and accessibility acceptance

- [ ] Rerun `npm run audit:installed:ui` against the exact immutable candidate
  and retain its candidate hash, twenty-five accepted screenshots, DOM/AX evidence,
  external-MCP result, graceful close, and residue-free uninstall report.
- [ ] Repeat the full failure-state sequence on the final signed candidate:
  endpoint collision/recovery, missing browser, missing/corrupt sidecar, real
  spawn failure, startup timeout with owned-process cleanup, exact sidecar
  restoration, and post-repair Runtime recovery.
- [ ] Complete keyboard-only testing for the remaining forms and management
  flows, then perform real assistive-technology acceptance; current critical
  path, screenshot, and AX-tree evidence must not be described as full WCAG
  compliance.
- [ ] Confirm contrast, readable hierarchy, reduced motion, responsive reflow,
  and lack of clipped/horizontal content again after every UI change without
  adding Agent permissions or bypassing scoped authority.
- [ ] Renderer and Electron/Runtime logs contain no unexpected errors or
  warnings throughout every accepted flow.

### NSIS installer and installed lifecycle

- [ ] Replace provisional `com.webfa.desktop` with the stable public `appId`
  approved for the product before the first public release; do not change it
  between updates.
- [ ] Visually verify the supplied WebFA application/installer icon, file
  metadata, publisher display name, Start menu and desktop shortcuts, taskbar,
  Tray, and uninstall presentation from a real installation; no default or
  malformed icon remains in the installed shell.
- [ ] Build and verify the unsigned NSIS candidate first:

  ```powershell
  npm run package:windows:unsigned
  ```

  This mode is a development-only installer/lifecycle gate. It may be run from
  an untagged or dirty review tree, does not claim formal provenance, and its
  output must not be published. Only the signed pipeline below enforces the
  clean exact-version tag and can produce a formal release candidate.

- [ ] On an otherwise clean Windows test user with PowerShell 7 and at least
  4 GiB free on its temporary volume, run the real installed lifecycle gate:

  ```powershell
  npm run smoke:installed:unsigned
  ```

  The command transiently creates current-user registry entries and desktop /
  Start-menu shortcuts, refuses to overwrite a pre-existing WebFA install, and
  must finish with all candidate-owned state removed.

- [ ] Install as a non-administrator into a clean per-user location; launch from
  Start menu and desktop shortcuts; verify a true cross-version upgrade over the
  previous supported version; visually confirm uninstall retains Profile data
  while removing the updater installer cache.
- [ ] Run the strict upgrade harness with a real older supported installer. For
  a formal signed candidate both installers must be signed and the historical
  signer thumbprint must be supplied:

  ```powershell
  npm run smoke:upgrade:windows -- `
    --previous <previous-installer.exe> `
    --previous-version <x.y.z> `
    --previous-mode signed `
    --previous-signer-sha1 <40-hex-thumbprint> `
    --current-mode signed
  ```
- [ ] From the installed location, repeat real MCP JSON-RPC, Profile isolation,
  Profile Bootstrap, Monitor/HumanControl, UI, port-collision, restart, and full
  process-tree exit smoke tests.

### Signing, timestamp, and publication

- [ ] Configure the approved Windows code-signing identity only through the
  release environment; no key, password, or certificate bundle is committed.
- [ ] Build the formal signed candidate:

  ```powershell
  npm run package:windows:signed
  ```

- [ ] Authenticode is `Valid` for the Desktop executable, bundled sidecar, and
  NSIS installer; all use the intended signer and include a valid trusted
  timestamp.
- [ ] The signed artifact is reinstalled and the complete installed lifecycle
  and UI smoke is repeated. Signing must not invalidate sidecar/ASAR checks.
- [ ] Generate `SHA256SUMS.txt` from the final signed installer, independently
  recompute the SHA-256 digest, and publish both through the release channel.
- [ ] Tag, release notes, package versions, executable metadata, installer name,
  public docs, and checksums all identify the same immutable release.
- [ ] Release notes state developer-preview limits, loopback-only trust model,
  unknown GET/navigation side-effect boundary, supported platform/browser
  prerequisites, Profile data compatibility, and that P13 remains deferred.
