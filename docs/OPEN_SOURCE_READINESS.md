# Open Source Readiness

Status: P1-P12 and Post-Core Profile Bootstrap are implemented. The
open-source Runtime baseline passed independent Grok acceptance on 2026-07-19,
and the 2026-08-02 source freeze was re-verified with source-external wheel
evidence. The evidence is recorded in `docs/reports/CURRENT_BASELINE.md`; it
becomes an immutable repository baseline only when the containing commit is
reviewed. This is not a public release certificate. Human preview UI is not a
product goal. Leftover Desktop code is developer residue; further Desktop
distribution work is paused. The former Durable Trace / Resume phase is
abandoned.

This document separates source-code readiness from a formal signed Windows
binary release. The repository can be reviewed and built as a developer preview,
but the final public Windows artifact remains blocked until the unchecked gates
in `RELEASE_CHECKLIST.md` pass for one immutable candidate.

## Release positioning

Public material must describe WebFA as:

- an agent-native internet Runtime, not a traditional human browser, DevTools
  wrapper, site API collection, scraping product, or autonomous agent;
- a local MCP-first Runtime with exactly five default Agent tools;
- a multi-Profile, multi-Session system in which each persistent Profile owns an
  isolated Chromium identity and at most one active writable Session;
- a system with connection-scoped Profile Grants, exclusive Session Leases,
  and generation-bound authority;
- a developer preview with no anti-bot bypass and no guarantee of safe
  unattended high-risk account activity;
- a system whose persistent Profile state survives restart but whose active
  Session task/authority state does not.

No README, package metadata, release note, screenshot, or demo may imply
durable task replay, page restoration, or resumable execution. Do not describe
human preview UI or Desktop Monitor as a product capability.

## Public entry points and protocol

Supported Python/frozen-sidecar entry points are:

- `webfa`
- `webfa-runtime`
- `webfa-mcp`
- `webfa mcp-config`
- `webfa doctor`
- `webfa login`

The default MCP tools remain exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Profile management, Profile Bootstrap, Cookie import, clone, Bundle operations,
policy editing, Monitor grants, and human takeover are protected local-control-
plane capabilities, not extra Agent tools. Legacy transaction and primitive
browser APIs remain opt-in/disabled and must not appear in the default Agent
integration path.

## Current implemented baseline

- P10 provides WebState/WebObjects, queryable observe, semantic operations,
  versions, ChangeSets, Runtime evidence, and a Managed Chromium BrowserHost.
- P11 provides SafetyContext, Runtime evidence escalation, deterministic safety
  policy, exact-scope single-use Step-up, scoped local resources, protected
  payment references, HumanControl takeover, and SafetyReceipt auditing.
- P12 provides persistent Profile catalog/storage, OS-backed Profile locks,
  dedicated Hosts, BrowserSessionRuntime/Supervisor, concurrent different-
  Profile Sessions, Agent Profile Grants, exclusive Session Leases, global
  Session/generation routes, Session-bound Monitor grants, and isolated human
  control.
- Shared-data-directory SQLite initialization is serialized across threads and
  processes for the complete additive schema/migration/seed sequence. Migration
  milestone and Provider seed rows commit atomically, every connection enforces
  foreign keys, and engine construction is thread-safe. A 12-process first-start
  regression, failed-seed rollback test, foreign-key integrity test, and pre-P12
  database preservation test protect the P12 catalog upgrade path.
- Active P12 Profile Grants and connection-exclusive Session Leases renew on
  successful five-tool activity while preserving their original identity and
  binding. Expired leases remain expired, current Profile binding policy is
  rechecked before renewal, and local tab IDs cannot bypass the connection-level
  lease. WebState, Monitor, and Control Center project the same outer Session
  Lease rather than the retired single-browser compatibility lease.
- Session Monitor projects the exact BrowserHost page used by the Agent. Its
  time-bounded HumanControlLease is bound to the Monitor connection, Profile,
  Session, tab, and Runtime generation; the duplicate-page Electron AuthSurface
  is retired.
- Post-Core Profile Bootstrap provides protected human login, redacted two-phase
  Cookie import, Profile clone, and Scrypt + AES-256-GCM encrypted Profile
  Bundles with a deliberately bounded identity-state scope.
- Python wheel/sdist include versioned YAML resources. The Windows frozen
  sidecar installs exact-version, SHA-256-locked third-party wheels with
  `--only-binary=:all: --require-hashes`, builds WebFA from the candidate source,
  and is smoke-tested outside the source tree.
- `webfa doctor` verifies the supported Web Object surface (`open_url`,
  `observe`, and semantic `act`) and no longer depends on the disabled legacy
  BrowserAction REST API. Generated MCP configuration identifies an external
  Agent and requires a distinct stable `WEBFA_AGENT_ID` per client; browser-host
  mode and HumanControl policy remain Runtime-host settings.
- Desktop has a static loopback Renderer server, exact Runtime identity checks,
  per-start control-token rotation, explicit process ownership/tree cleanup,
  packaged `WEBFA_HOME` fixed to Electron `userData`, an exact ASAR payload
  verifier, pinned Electron archive checksum, and hardened fuses.
- Control Center and Session Monitor share a responsive, keyboard-visible,
  reduced-motion-aware visual system. The installed audit now captures desktop
  and 390px states, DOM/AX evidence, skip links, drawer focus loops/restoration,
  keyboard-only desktop/mobile HumanControl acquisition and release, failure
  recovery actions, desktop-sidebar restoration, and a real external MCP Agent
  session/live Monitor projection. Every new immutable candidate must rerun that
  audit; remaining forms and management flows still need full keyboard coverage
  and real assistive-technology acceptance.
- Safety Center management forms use visible labels and semantic section
  headings. Production-Renderer captures cover the upper and lower form regions
  at desktop and 390px widths with no horizontal overflow; compact drawers use
  an opaque management surface so Runtime content cannot bleed through controls.

## Security and disclosure hygiene

- `SECURITY.md` documents the loopback trust model, multi-Profile/Session lease
  boundaries, exact Step-up enforcement, Profile Bootstrap boundary, restart
  invalidation, and the unknown GET/navigation side-effect limitation.
- Agent schemas and docs do not expose credentials, cookies/storage, tokens,
  raw payment secrets, local paths, raw CDP/Playwright, selectors/XPath/evaluate,
  full DOM, or full HTML.
- Local Visualizer/Monitor APIs use authority separate from Agent MCP/REST.
- Personal filesystem paths, account names, private screenshots, local reports,
  generated clipboard artifacts, build output, caches, virtualenvs, and local
  databases are excluded from public source.
- Loopback Runtime calls bypass system proxy settings where required, so local
  Agent integration is not redirected through user-level proxies.
- Historical transaction/provider material is clearly legacy/abandoned and is
  absent from the default public MCP surface.

The Python distribution identifier remains the historical
`webfa-desktop-runtime` name for compatibility with existing tags, entry-point
consumers, sidecar manifests, and upgrade checks. This identifier is not the
product definition. A future rename must be an explicit package migration with
redirect/upgrade handling; it must not be slipped into a closure patch.

## Optional Desktop distribution readiness

This section records machinery that already exists. It is not the current
product-development priority and none of its formal Windows publication gates
blocks an open-source Runtime source or wheel release.

Implemented release machinery includes:

- a SHA-256-locked Windows Python wheel set, pinned CPython/PyInstaller, and
  exact Node/npm/Electron dependencies;
- an exact Node/npm engine check, fresh `npm ci`, explicit `npm audit`, and a
  sanitized release environment at every Windows packaging entry;
- source-free onedir sidecar staging and real frozen MCP stdio smoke;
- exact Electron archive checksum verification and a packaged SHA-256 toolchain
  lock for Electron Builder, NSIS, NSIS resources, and 7-Zip;
- static Renderer and Electron compilation;
- parsed, deep structural validation of unsigned and signed electron-builder
  configuration;
- a generated build manifest binding dependency locks, the Electron archive,
  icon, complete sidecar and Authenticode-invariant executable payload, and
  canonical Desktop archive input;
- exact ASAR file-set and Electron/Renderer byte verification, file-by-file
  binding of unchanged Electron runtime/legal files, a complete unpacked-file
  allowlist, post-builder sidecar/ASAR manifest binding, and hardened fuses;
- packaged `WEBFA_HOME = app.getPath("userData")` isolation, including a smoke
  assertion that an inherited hostile value is ignored;
- an automatically run packaged-only unpacked lifecycle smoke covering Renderer
  load, Runtime identity/ownership and health, icon load, bounded shutdown, port
  closure, Renderer-server cleanup, and packaged-process cleanup;
- unpacked Windows packaging and an x64 per-user, non-elevating NSIS target with
  publishing, updater metadata, differential packages, and the elevation helper disabled;
- a validated WebFA multi-resolution application/installer icon wired into the
  Desktop, sidecar, BrowserWindows, Tray, installer, and uninstaller;
- separate unsigned and signed build modes;
- PE/NSIS physical-envelope, version-identity, embedded-7z integrity, and full
  installer-payload verification, plus Authenticode signer/timestamp checks and
  final installer SHA-256 output;
- a manifest-bound NSIS hook that rejects a temporary volume with less than
  4 GiB free before extraction and removes only the updater installer cache on
  uninstall; and
- a real installed-artifact smoke for current-user install, complete payload,
  registry/shortcuts/cache, installed lifecycle, same-version reinstall, and
  residue-free uninstall;
- a real installed UI/MCP audit that captures empty and live Agent states,
  responsive Control Center/Monitor layouts, structured accessibility evidence,
  and the exact external five-tool MCP flow against the Desktop-owned Runtime;
  and
- a strict cross-version harness that rejects non-older artifacts and `appId`
  migration, verifies historical signing and packaged user-data identity,
  rejects stale upgraded files, runs both installed versions against the same
  owned persistent data tree, proves an exact Profile sentinel survives current
  Runtime startup and uninstall, and cleans only owned state. It remains
  unpassed until a real prior supported installer is supplied.

The unsigned mode is deliberately a development-only NSIS structure and
lifecycle gate: it may run on an untagged review tree, does not run the formal
clean-tag provenance check, and must never be published. Only the signed mode
enforces exact-tag provenance and can qualify an artifact as a formal Windows
release candidate.

The presence of this machinery does not by itself make a Desktop candidate
publishable. A formal Windows Desktop release remains blocked until all of these
are complete for the same candidate:

- stable product `appId` and real installed-shell validation of the supplied
  WebFA icon, product metadata, shortcuts, taskbar/Tray, and uninstaller;
- clean full Python, Node, contract, wheel, sidecar, Renderer, and Electron test
  results;
- hostile/error-state and full process-tree exit checks from the packaged app;
- installed offline and remaining form/management UI acceptance, including
  complete keyboard and real assistive-technology evidence (the current audit
  already covers installed missing-browser and bounded startup/recovery actions);
- clean standard-user visible-shell acceptance, true cross-version upgrade from
  the previous supported release, and visually confirmed retained Profile-data
  behavior (the automated same-version installed lifecycle already passes);
- valid Authenticode signatures and trusted timestamps on Desktop, sidecar, and
  NSIS installer;
- independently verified SHA-256 checksum and consistent immutable release
  version/tag/notes.

Other operating systems remain unsupported for formal binary publication until
they have equivalent sidecar, packaging, signing/notarization, UI, install, and
shutdown evidence.

## Candidate verification

Run the artifact-specific gates in `RELEASE_CHECKLIST.md`. Runtime source/wheel
verification includes at minimum:

```powershell
python -m pytest -q
python -m build
```

The built wheel must then be installed into a clean virtual environment and its
Runtime identity, resources, `webfa doctor`, five-tool MCP surface, and local
open/observe/act flow verified outside the repository.

Only when producing the optional Windows Desktop preview, additionally run:

```powershell
npm run test:electron-process
npm run typecheck:renderer
npm run typecheck:electron
npm run build:sidecar:onedir
npm run build:renderer
npm run build:electron
npm run verify:release-inputs
npm run package:unpacked
npm run package:windows:unsigned
npm run audit:installed:ui
```

`npm run package:unpacked` enforces the pinned Node/npm versions, creates a fresh
lockfile install, runs the audit and release-input build, then automatically runs
both the unpacked integrity verifier and packaged lifecycle smoke. These are
implemented mechanisms, but their result must still be recorded for the exact
immutable candidate being considered.

If the optional preview is later promoted to a formal Windows candidate, it
additionally requires the signed NSIS pipeline,
installed-artifact MCP/UI/lifecycle smoke, signature/timestamp verification, and
final checksum publication. Do not substitute an earlier local artifact, mocked
transport, source-mode run, or static screenshot for those gates.
