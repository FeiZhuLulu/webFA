# Optional WebFA Runtime Manager Distribution Architecture

Status: implemented Windows developer-preview architecture; optional to the open-source Runtime  
Updated: 2026-07-18

## 1. Purpose and boundary

WebFA Desktop is an optional lightweight local host and human management surface for the agent-native Runtime. It starts and observes WebFA, helps external Agents connect, manages identity and approval boundaries, and enables constrained human takeover. It is not an Agent, does not own an external Agent's MCP stdio connection, and is not a traditional browser shell.

The Desktop deliberately contains no model, planner, task queue, goal loop,
agent memory, site-selection logic, or autonomous execution policy. It does not
broker work between Agents or become the caller of WebFA's public Agent API.
Codex, Claude, custom Agents, and other clients remain independent users of the
same Runtime contract.

The production distribution must preserve the same public product model as source development:

- one local Runtime process can host multiple isolated Profiles and Sessions;
- each external Agent client owns its own MCP stdio bridge and connection identity;
- the Desktop owns only the Runtime child it started, its protected control token, the packaged Renderer, and Monitor windows;
- BrowserHost processes remain Runtime-owned descendants and must be closed before Runtime exit;
- Session Monitor projects the same BrowserHost page and may forward local input only while its exact Session-scoped HumanControlLease is active; the duplicate-page Electron AuthSurface is retired;
- Human preview UI is not a product goal. Durable task resume is not part of this leftover distribution work.

## 2. Optional artifact model

When a desktop preview is built, it is one versioned platform artifact containing:

1. Electron main/preload JavaScript;
2. a static production export of the Control Center and Session Monitor Renderer;
3. one complete PyInstaller `onedir` sidecar bundle containing the `webfa` entry executable, Python interpreter, Runtime, MCP bridge, schemas, versioned resource definitions, and every adjacent native/runtime file emitted for that bundle;
4. application metadata and platform assets required by the installer;
5. a build manifest, SPDX SBOM, and third-party notice bound to the candidate
   release inputs and copied into the packaged legal resources.

The installable Desktop artifact must copy the verified `onedir` bundle intact beneath its application resources and invoke that bundle's `webfa.exe`. The bundle is a single versioned release unit: packaging must not cherry-pick the executable or selected adjacent files from it.

A PyInstaller `onefile` build remains useful as a separately verified, independently portable CLI/MCP artifact. Its temporary extraction model and standalone smoke result do not satisfy the Desktop payload, installed-layout, startup, shutdown, or uninstall gates, so it is not the formal sidecar payload of the Electron/NSIS distribution.

The Python wheel remains a separately supported developer and server/CLI artifact. Both artifacts expose the same Runtime and five-tool MCP contracts and use the same release version.

Chromium is not silently downloaded at application startup. The initial Windows developer-preview artifact discovers an installed Chrome, Edge, or explicitly configured Chromium executable. Missing-browser state is reported as a prerequisite failure in the Control Center and `webfa doctor`.

## 3. Process ownership

### 3.1 Desktop-owned processes

Electron may start exactly one sidecar command:

```text
webfa runtime --host 127.0.0.1 --port 8787
```

The Runtime owns BrowserSession workers and BrowserHost process trees. Electron waits for the Runtime process tree to terminate before final quit. It never kills or stops a Runtime process it did not start.

### 3.2 Agent-owned processes

An Agent's MCP client starts:

```text
webfa mcp --runtime-url http://127.0.0.1:8787
```

That stdio process belongs to the Agent client. Its stdin/stdout are the MCP transport. Desktop must not spawn an unconnected stdio bridge, drain its protocol output, or claim that such a process represents Agent connectivity.

If the Runtime is unavailable, the sidecar MCP command may start the sibling sidecar in Runtime mode and owns only that auto-started Runtime. Installed Python entry points preserve the existing `webfa-mcp` compatibility command.

MCP auto-start is a loopback-only convenience with explicit cross-process ownership coordination:

- `localhost` and `127.0.0.1` are normalized into one endpoint ownership domain;
- an operating-system file lock serializes probe, spawn, metadata, lease, and last-owner shutdown operations for that endpoint;
- each MCP client holds a lease tied to both its PID and a stable process identity, not to PID existence alone;
- stale leases are removed only after their stable process identity no longer matches;
- the last live lease may stop only the Runtime whose matching auto-start metadata and process identity prove MCP ownership;
- an external Runtime, a Desktop-owned Runtime, ambiguous metadata, or a reused PID is never terminated by MCP cleanup.

### 3.3 Human UI representation

The Control Center reports:

- Runtime process state and health;
- MCP capability availability from `/v1/mcp/status`;
- active Agent/Profile/Session/Lease state from Runtime authority state;
- copyable MCP client configuration.

It does not expose Start/Stop/Restart controls for a desktop-owned MCP server because no such server exists in the final model.

## 4. Renderer delivery and origin

The Renderer is built with Next static export. Electron serves the exported directory from an Electron-owned HTTP server bound to `127.0.0.1` on an operating-system-assigned port. It is never loaded from a developer server or `file://` in a production package.

The server:

- accepts only loopback connections;
- maps `/` and `/monitor/` to exported HTML;
- serves only files beneath the immutable export root;
- rejects traversal, directory ambiguity, unsupported methods, and missing files;
- supplies explicit content types and restrictive security headers;
- is stopped during Electron shutdown.

The selected origin is passed to Runtime as the only packaged Console/Monitor origin. Electron main creates a fresh high-entropy control token for every Desktop-owned Runtime start. The token is issued through validated IPC only while that exact owned instance is verified running, is rotated on every restart, and is cleared on stop, exit, failed startup, or ownership loss. It is never embedded into static assets, persisted for reuse, or issued for an external Runtime.

## 5. Runtime discovery and port collisions

The default Runtime endpoint remains `http://127.0.0.1:8787` for compatibility with wheel entry points and existing Agent configurations.

Before starting its sidecar, Desktop probes the endpoint:

- if the port is unused, Desktop starts and owns the sidecar;
- if a compatible Runtime is already present, Desktop does not silently adopt control authority or terminate it; it reports that an external Runtime occupies the endpoint and requires an explicit supported attach flow or a different configured port;
- if another service occupies the port, startup fails with a bounded collision state;
- a failed or ambiguous probe never authorizes protected visualizer access.

An explicit `WEBFA_API_PORT` remains available for development and controlled deployment. Generated MCP configuration always uses the actual selected endpoint.

Runtime compatibility and ownership are established by the complete health identity tuple: exact `product`, exact `release_version`, exact `protocol_version`, and a syntactically valid `instance_id`. A Desktop spawn additionally injects a unique expected instance ID and must observe that exact value before claiming ownership or issuing its control token. A missing or mismatched field is a bounded collision/identity failure; matching product or protocol alone is never sufficient authority.

## 6. Sidecar command contract

The frozen sidecar is a single multi-call executable:

- `webfa runtime [--host HOST] [--port PORT]`
- `webfa mcp [--runtime-url URL] [--no-auto-start]`
- `webfa status`, `paths`, `doctor`, `login`, and `mcp-config`

Source and wheel console scripts delegate to the same command functions. Frozen-mode Runtime auto-start uses the sibling/multi-call executable instead of `python -m uvicorn`.

The sidecar build must include all imported packages and `webfa_resources`. Every third-party Windows wheel is exact-versioned and SHA-256 pinned in `packaging/python-windows-release-lock.txt`, and installation uses `--only-binary=:all: --require-hashes`. The WebFA wheel is built from the candidate source tree and installed separately with `--no-deps`. Startup fails closed if packaged policy or transaction data is absent.

## 7. Data, identity, and security boundaries

- Source and standalone CLI runs keep persistent state under `WEBFA_HOME`,
  defaulting to the platform WebFA application-data directory.
- Packaged Desktop explicitly sets the bundled Runtime's `WEBFA_HOME` to
  Electron `app.getPath("userData")`; it ignores an inherited parent value and
  uses the same directory as its working directory. Profile/Session writes must
  not escape that Desktop-owned root or enter program files.
- Packaged program files and static Renderer assets are immutable and never used for Profile or Session writes.
- Renderer HTTP assets do not contain the visualizer token, Profile secrets, bundle passphrases, MCP traffic, or browser storage.
- Profile Bundle file access remains native main-process streaming with sender and origin validation.
- The Monitor receives only a scoped, expiring grant bound to the exact Profile,
  Session, and Runtime generation. HumanControlLease additionally binds the
  authenticated Monitor connection and active tab, forwards input to the same
  BrowserHost page, and ends on release, expiry, revocation, disconnect, or
  Monitor closure.
- Sidecar stdout/stderr diagnostics must not copy MCP JSON-RPC traffic or secret-bearing request bodies.
- Application shutdown stops the Renderer server and every Desktop-owned process tree, but never external Agent-owned MCP processes.

## 8. Build pipeline

The production build is ordered and fail-fast:

1. sanitize inherited build/control variables, require the exact Node and npm
   engine versions, create a fresh lockfile install with `npm ci`, and run
   `npm audit`;
2. run Python tests and package-resource contracts;
3. install the SHA-256-locked third-party wheel set, build the current WebFA
   wheel, freeze the source-free `onedir` sidecar, and run its resource/MCP
   smoke outside the source tree;
4. type-check and statically export the Renderer;
5. type-check/build Electron main and preloads;
6. prepare the pinned Electron archive and generate the build manifest, SPDX
   SBOM, third-party notice, and the packaged Windows toolchain lock for Electron
   Builder, NSIS, NSIS resources, and 7-Zip; the manifest also binds the audited
   NSIS initialization/uninstall hook;
7. parse both builder YAML files and compare their complete effective structures,
   then verify versions, dependency locks, icon, sidecar payload, Desktop archive
   inputs, Electron checksum, and all required release files;
8. create an unpacked Electron application;
9. verify the exact ASAR file set and asset bytes, reduced application manifest,
   every unchanged Electron runtime/legal file against the pinned archive, the
   complete unpacked file allowlist, packaged sidecar payload, build-manifest
   bindings, embedded icons, and fuses;
10. run the packaged-only Renderer/Runtime/health/quit lifecycle smoke, including
    hostile inherited-`WEBFA_HOME`, port-closure, Renderer-server, and process-
    cleanup assertions;
11. create the platform installer/archive;
12. verify artifact mode and Windows identity, PE/NSIS physical structure,
    embedded 7z integrity and its complete match to `win-unpacked`, signatures
    where required, and final checksums;
13. on a clean Windows test user, run the explicit installed-artifact gate:
    verify temporary-volume capacity before mutation, install into an owned
    current-user directory, compare all release files, validate registry,
    shortcuts and updater cache, launch/stop the installed lifecycle, repeat a
    same-version reinstall, and prove uninstall removes candidate-owned state.

No packaging target may fall back to repository source, a globally installed Python package, a development Renderer URL, or an absent sidecar.

## 9. Implementation status and gates not yet passed

The repository now implements the intended ownership primitives and build shape. The formal release-input pipeline selects PyInstaller `onedir`, installs a SHA-256-locked third-party wheel set, builds WebFA from the candidate source, and gives the frozen sidecar resource/MCP smoke coverage. Windows packaging enforces exact Node/npm engines, a fresh `npm ci` and audit, a sanitized environment, a packaged external-toolchain lock, parsed full-structure builder configuration, and a build manifest that binds dependency/toolchain locks, Electron, the application icon, the audited NSIS hook, the full sidecar and Authenticode-invariant executable payload, and canonical Desktop archive inputs. The unpacked verifier checks exact ASAR content, the pinned Electron runtime/legal inventory, a closed file allowlist, and post-builder manifest binding; the NSIS verifier checks identity, physical envelope, and the full embedded application payload. The packaged-only lifecycle smoke proves Renderer load, Runtime identity/ownership and health, forced `WEBFA_HOME=userData`, icon loading, and bounded process/server/port cleanup. A separate installed-artifact smoke proves current-user installation, full payload identity, registry/shortcut/cache identity, installed launch/quit, same-version reinstall, and residue-free uninstall. The installed UI audit additionally performs a real install, captures desktop and 390px Control Center/Monitor states with DOM and accessibility-tree evidence, launches the Runtime-advertised installed sidecar through a real external MCP client, completes the five-tool open/observe/act/observe flow, and proves both UI surfaces project the same authoritative Agent/Profile/Session and live BrowserHost frame before graceful shutdown and uninstall. The installer fails before extraction below 4 GiB of temporary-volume free space, and its custom uninstaller removes the release cache without entering Profile data. Electron and MCP require the exact product/release/protocol/instance handshake; Desktop control tokens rotate per owned Runtime generation and are cleared on every terminal path; and MCP auto-start uses an endpoint lock, leases, stable process identities, and last-owner cleanup that excludes external/Desktop Runtime processes. A strict cross-version harness verifies historical signer, `appId`, packaged user-data identity, both installed Runtime lifecycles, exact upgraded payload, and Profile-sentinel survival across startup and uninstall, but cannot close the upgrade gate without a real older supported installer.

The current installed UI audit retains 25 accepted states and keeps the real MCP
stdio Session alive while Control Center, Monitor, and HumanControl are examined.
It proves keyboard-only skip links, compact focus traps and restoration,
desktop/mobile HumanControl escape/re-entry/release, frame-independent lease
release, five failure-recovery buttons, and restoration of independent desktop
sidebars after compact layout.

These results establish a usable optional developer preview, not a formal Windows product release. They do not block a source/wheel release of the open-source Runtime. If the Desktop is later promoted to an independently published Windows artifact, the following distribution evidence is still required:

- offline and the remaining form/management flows still need complete keyboard
  and real assistive-technology evidence. The accepted current audit covers
  empty/live/loading, missing-browser, bounded startup and recovery states,
  desktop/mobile HumanControl, responsive drawers, focus restoration, labels,
  overflow, real external MCP state, and the live Monitor projection, but is not
  a full WCAG claim;
- a clean standard-user VM run of the installed gate, a true cross-version
  upgrade from the previous supported release, and visible shell validation;
- a production code signature and trust verification for the installer and executables;
- a confirmed public application identity/app ID rather than a provisional identifier;
- installed-shell visual verification of the supplied WebFA icon and product
  metadata across Start menu/desktop shortcuts, taskbar, Tray, and uninstaller;
- packaged missing-browser behavior proven in the real UI and `doctor`, with a useful bounded prerequisite state;
- packaged Profile-data placement and preservation/removal behavior proven against the platform application-data root, including uninstall behavior and absence of writes beneath program files.

Passing unit tests, type checks, static export, release-input and unpacked-content
verification, the automatic packaged lifecycle smoke, a frozen sidecar smoke, or
a standalone `onefile` run does not substitute for these installed-artifact
gates. Each automated gate must also be rerun for the exact immutable candidate.

## 10. Acceptance criteria

The optional desktop distribution is ready for a formal public Windows release only when all of the following are proven from the unpacked or installed artifact outside the repository:

- Control Center and Monitor assets load with no development server;
- Session Monitor controls only the exact existing BrowserHost page under a
  valid HumanControlLease and never recreates the retired duplicate AuthSurface;
- Runtime starts from the bundled sidecar and reports the packaged version;
- third-party sidecar wheels are installed only from the exact hash lock and the
  candidate WebFA wheel is built from the intended source revision;
- the sidecar is the complete verified `onedir` bundle, and no Desktop path silently substitutes a `onefile` executable or repository/global Python files;
- the health handshake matches exact product, release, protocol, and the expected Runtime instance before Desktop claims ownership or exposes a control token;
- every Desktop-owned Runtime restart rotates the control token, and stop/failure/exit makes the previous token unavailable;
- all three current versioned transaction resources load from the sidecar;
- the default MCP surface remains exactly five tools;
- generated MCP configuration invokes the bundled multi-call sidecar in `mcp` mode;
- a real MCP client can initialize, list tools, open a local page, observe, act, and observe the result;
- concurrent MCP clients serialize auto-start through one endpoint lock, retain independent live leases, recover stale leases by stable process identity, and only the last live owner stops the MCP-owned Runtime;
- MCP cleanup never stops a compatible external Runtime, Desktop-owned Runtime, ambiguous process, or reused PID;
- Desktop shows the real active Agent/Profile/Session state, not an orphan process state;
- packaged Profile data is written only beneath Electron `userData`, regardless
  of an inherited `WEBFA_HOME`, and never beneath program files;
- the packaged ASAR and sidecar Authenticode-invariant executable payload match
  their build-manifest bindings after electron-builder and, where applicable,
  signing;
- the supplied WebFA icon is embedded and appears correctly in every installed
  Windows shell surface without a default or malformed fallback;
- renderer traversal and untrusted IPC attempts fail closed;
- closing Desktop reaps its Renderer server, Runtime, BrowserHost, and descendants;
- port collision, missing sidecar, missing browser, corrupt resources, and Runtime startup failure each produce a useful bounded UI state;
- Windows unpacked and installer smoke checks pass; other platforms remain blocked until their equivalent sidecar, signing, and smoke checks exist.

## 11. Incremental delivery rule

Desktop maintenance must preserve this lightweight host/management boundary and must not add Agent behavior. Further distribution work is deferred until the Runtime roadmap calls for it. Development-only fallbacks may remain behind explicit source-mode detection; they must never be selected by a production package.
