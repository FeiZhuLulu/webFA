# Profile Bootstrap Adversarial Review

Status: reviewed and hardened

Date: 2026-07-14

## 1. Review Question

This review asked two separate questions:

1. Does Profile Bootstrap introduce security, integrity, lifecycle, or compatibility defects?
2. Does Cookie import, Profile clone, or Bundle export/restore move WebFA away from its core definition as an agent-native internet runtime?

The review covered:

```text
Managed Chromium launch and CDP access
Profile storage transfer policy
clone snapshot integrity
Bundle encryption and archive validation
passphrase lifetime and API validation
temporary plaintext artifacts
cross-platform restoration claims
Desktop/browser streaming boundaries
Agent MCP and WebState exposure
```

## 2. Direction Finding

Profile Bootstrap is aligned with WebFA only under this definition:

> It is a protected local control plane for provisioning the durable internet identity that an Agent uses through WebFA.

It is not:

```text
a normal human browser profile manager
a Chrome backup product
a browsing-history migration tool
a password-vault exporter
an extension migration system
an Agent-facing Cookie or storage API
```

The implementation remains directionally aligned because:

- Agent interaction still uses exactly five semantic WebFA tools;
- Profile Bootstrap is absent from MCP, WebState, Monitor events, and SafetyReceipt;
- the user performs identity provisioning locally and explicitly;
- Profile, Session, Agent authorization, and human control remain separate objects;
- restored or imported storage never automatically grants an Agent access;
- WebFA does not claim that copied files imply a successfully authenticated account.

The review nevertheless found that the initial clone/Bundle transfer boundary was too close to a full Chrome profile backup. That boundary has been corrected.

## 3. Finding: CDP Origin Was Wildcarded

Previous behavior:

```text
--remote-allow-origins=*
```

This contradicted WebFA's controlled Runtime boundary and left an unnecessary broad CDP WebSocket Origin allowance.

Correction:

```text
--remote-allow-origins=https://runtime.webfa.invalid
CDP client Origin: https://runtime.webfa.invalid
--disable-extensions
```

Managed Chromium now accepts the WebFA-specific CDP Origin rather than a wildcard. Extensions are disabled because an imported or cloned extension environment is outside the trusted Agent Runtime model.

## 4. Finding: One user-data-dir Could Contain Several Chrome Identities

Chromium may store several subprofiles inside one user-data-dir:

```text
Default
Profile 1
Profile 2
Guest Profile
System Profile
```

The frozen WebFA model requires:

```text
one WebFA BrowserProfile = one explicit internet identity
```

Correction:

```text
--profile-directory=Default
```

Profile transfer also rejects every non-Default Chromium subprofile. A WebFA Profile can no longer silently contain several independently selectable Chrome identities.

## 5. Finding: Clone and Bundle Included Human-Browser Data

The initial transfer walker excluded runtime locks and caches but otherwise copied nearly the whole Chromium user-data-dir. That could include data unrelated to Agent internet identity:

```text
History and Visited Links
Bookmarks and Favicons
Top Sites and Shortcuts
Login Data password databases
Web Data and autofill/payment metadata
open-tab and Session restoration files
Extensions and extension settings
other Chromium subprofiles
```

This was a product-direction problem as well as a privacy problem. WebFA needs durable website identity, not a copy of a person's complete browser life.

Correction:

The shared transfer policy now retains Default-profile website state while excluding:

- browser history, navigation suggestions, bookmarks, favicons, top sites, and shortcuts;
- password, account-password, affiliation, autofill, and account-personal databases;
- current/last tab and Session restoration data;
- extensions and all extension state;
- Web Applications and Sync data;
- non-Default Chromium subprofiles;
- runtime, shader, GPU, component, segmentation, download, and browser caches;
- selected reporting and transport-policy state.

The policy is applied twice:

1. during clone/Bundle export traversal;
2. independently during Bundle restore validation.

An authenticated external Bundle containing excluded files is rejected rather than trusted.

## 6. Finding: Clone Fingerprint Did Not Bind File Contents

The original storage snapshot used:

```text
relative path
entry type
file size
mtime_ns
```

An equal-size modification with a restored timestamp could evade change detection. A copied file could also be corrupted without changing the metadata fingerprint.

Correction:

Every included file is now streamed through SHA-256 during snapshot creation. The snapshot includes the content digest and performs stat checks before and after hashing. A concurrent change during hashing fails closed.

Commit and post-copy validation therefore bind:

```text
path + type + size + timestamp + file contents
```

## 7. Finding: Restore Preview Retained the Passphrase

The initial restore preview retained the plaintext passphrase in `_PendingRestore` for up to the preview TTL.

Correction:

- Runtime retains the encrypted upload and authenticated manifest only.
- The passphrase is discarded immediately after preview validation.
- The user must re-enter the passphrase at restore commit.
- A wrong commit passphrase does not consume the preview, allowing an explicit corrected retry.

This reduces secret lifetime and independently authorizes final decryption.

## 8. Finding: Passphrase in JSON Could Appear in Validation Diagnostics

Pydantic/FastAPI request-body validation may include rejected input in a default 422 response. A malformed passphrase field could therefore be echoed.

Correction:

- Bundle passphrases are carried only by the protected local `X-WebFA-Bundle-Passphrase` header.
- Passphrases are absent from Pydantic body models and OpenAPI request-body schemas.
- Runtime has a global validation handler that returns only safe structural fields:

```text
type
location
message
```

Rejected input values are never included.

## 9. Finding: Crash-Orphaned Plaintext ZIP Lifetime

Bundle export and restore use a temporary plaintext ZIP during bounded local validation. Normal paths deleted the file, but service startup previously retained recent orphaned artifacts for up to 24 hours.

Because preview state is intentionally memory-only, no temporary artifact from a previous Runtime process can remain valid.

Correction:

`ProfileBundleService` now takes a cross-process exclusive lock for its dedicated temporary store, then clears that store:

- at service startup;
- at service shutdown.

A second Runtime cannot purge or reuse files belonging to an active first Runtime. Normal operation still deletes plaintext files immediately after use. This does not eliminate the short plaintext-on-disk window during processing, but it prevents crash artifacts from surviving the next valid service start.

## 10. Finding: Restore Semantics Could Be Overstated

Chromium credentials and website sessions may be bound to:

```text
OS user encryption
hardware-backed credential storage
device identity
browser build
website device/session policy
```

File restoration cannot guarantee account authentication, especially across machines or operating systems.

Correction:

Bundle manifest and restore preview now include:

```text
source_platform
current_platform
restoration_scope = browser_storage_only
compatibility_warning
```

The UI explicitly states that browser storage may restore while account login remains unusable. Cookie import similarly reports `cookies_imported`, never `login_restored`.

## 11. Finding: Browser Fallback Could Exhaust Renderer Memory

The Electron path streams Bundle files through the main process. The development browser fallback uses Blob/File objects and therefore loads large data into browser memory.

Correction:

The browser fallback is capped at 256 MiB. Larger Bundle export/restore requires WebFA Desktop's streaming bridge.

## 12. Preserved Security and Product Invariants

After hardening:

1. The default Agent surface remains exactly five MCP tools.
2. Agent requests cannot import, export, clone, list, or read browser storage.
3. Agent requests cannot select a user-data-dir or Chrome subprofile.
4. One WebFA BrowserProfile maps to the Chromium `Default` subprofile only.
5. Extensions are disabled in Managed Chromium.
6. CDP accepts a WebFA-specific Origin, not a wildcard.
7. Clone and Bundle transport website identity, not browser history or a password vault.
8. Restored identities receive no Agent bindings, allowed origins, Safety policy, or Financial policy.
9. Profile maintenance requires an inactive Profile and an exclusive mutation lease.
10. Bundle restore always creates a new Profile and never overwrites an existing identity.
11. Storage restoration is not reported as authenticated-account recovery.
12. Human Control and Monitor remain Session-scoped projections of the same real Host.

## 13. Accepted Remaining Boundaries

The review does not claim that raw Chromium storage transfer is the final ideal abstraction.

Accepted current boundaries:

- `Local State` and selected `Preferences` remain because Chromium may require them for website identity and credential decryption; they stay encrypted inside the Bundle and never enter Agent state.
- A plaintext ZIP exists briefly on local disk during Bundle processing. It is mode-restricted, immediately deleted on normal paths, and fully purged at next service startup after a crash.
- Cross-platform and cross-device account recovery is best-effort only.
- Browser extensions are not part of WebFA identity and are disabled rather than migrated.
- CacheStorage still has a known verification limitation in the current headless Chromium environment.

A future identity-store abstraction could export semantic per-origin state rather than selected Chromium files. That would be a further hardening layer, not a reason to expose storage to the Agent.

## 14. Validation

Final review validation:

```text
Python unit/contract: 397 passed, 1 skipped
Python integration:   123 passed
Python total:         520 passed, 1 skipped
Electron typecheck:   passed
Renderer typecheck:   passed
Electron build:       passed
Next production build: passed
Python sdist/wheel:   passed
Git diff check:       passed
```

The skipped test is the existing Windows environment-dependent symbolic-link case. The only warnings are the existing `websockets.legacy` and Uvicorn legacy WebSocket protocol deprecations.

## 15. Review Decision

The Profile Bootstrap direction is accepted after the corrections in this review.

The correct conceptual boundary is:

```text
Profile Bootstrap
  = user-controlled provisioning of an Agent internet identity

not

Profile Bootstrap
  = a traditional browser profile product
```

Cookie import, identity-scoped clone, and encrypted identity-scoped Bundle remain useful because they let Agents operate as real internet users under different durable accounts. Their placement in the protected local control plane preserves WebFA's core architecture.
