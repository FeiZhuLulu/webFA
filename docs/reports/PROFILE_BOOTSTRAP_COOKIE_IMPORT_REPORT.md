# Profile Bootstrap Cookie Import Report

Status: implemented and accepted

Date: 2026-07-13

## 1. Phase Scope

This phase implements the first protected Post-Core Profile Bootstrap capability:

```text
Cookie import into an inactive persistent BrowserProfile
```

It consumes the accepted P12 Profile/Session isolation model and does not change the Agent-facing browser model.

The default MCP surface remains exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

There is no Agent `import_cookies`, Cookie read, storage read, CDP, Profile-management, or Session-management tool.

## 2. Trust Boundary

Cookie import exists only on the local protected control plane.

The control flow is:

```text
local user selects a file
  -> protected Visualizer control API
  -> bounded parser in Runtime memory
  -> redacted preview
  -> explicit user confirmation
  -> inactive target Profile
  -> ProfileMutationLease
  -> ProfileMaintenanceHost
  -> CDP Storage.setCookies
  -> CDP Storage.getCookies verification
  -> graceful Host close
  -> Profile metadata update
  -> secret-free audit event
  -> lock release
```

The Visualizer control token is required for every preview, cancel, Session-close, and commit operation.

The preview token is additionally bound to:

```text
control-token digest
profile_id
profile_version
expiry
```

The raw control token is not stored.

## 3. Supported Inputs

The parser supports:

- common JSON Cookie export arrays;
- JSON objects containing a `cookies` array;
- Netscape `cookies.txt` format;
- `#HttpOnly_` Netscape entries;
- UTF-8 and UTF-8 BOM text.

The parser accepts the relevant Chromium `Network.CookieParam` fields where present:

```text
name
value
url / domain
path
secure
httpOnly
sameSite
expires
priority
sourceScheme
sourcePort
partitionKey
```

Partitioned Cookie input supports the CHIPS partition key shape:

```text
topLevelSite
hasCrossSiteAncestor
```

## 4. Input Hardening

Limits:

```text
maximum file size: 5 MiB
maximum entries:   5000
preview TTL:       10 minutes
pending previews:  20 per Runtime
```

Validation includes:

- Cookie name syntax and length;
- Cookie value length and control characters;
- URL scheme and hostname;
- domain normalization and IDNA conversion;
- path syntax;
- expiry normalization and expired-entry rejection;
- SameSite values;
- `SameSite=None` requiring `Secure`;
- `__Secure-` and `__Host-` prefix constraints;
- source port range;
- partition-key URL validation;
- duplicate scope replacement.

Invalid entries are rejected individually. The preview reports only safe warning codes and counts.

## 5. Secret-Free Preview

The preview contains:

```text
source format
entry count
accepted / rejected count
domain count and domain summary
Secure count
HttpOnly count
session / persistent count
partitioned count
safe warning codes
expiry time
```

It never contains:

- Cookie values;
- Cookie names;
- complete Cookie header strings;
- Profile filesystem paths;
- CDP request payloads;
- browser storage values.

The selected local file is sent directly as an octet-stream request body. It is not converted into an Agent resource grant or inserted into WebState.

## 6. ProfileMutationLease

`ProfileMutationLease` shares the same OS-backed `ProfileProcessLock` used by normal persistent BrowserSession hosts.

Therefore these states are mutually exclusive:

```text
normal BrowserSession Host
Cookie-import Maintenance Host
Profile archive mutation
future Profile clone/restore mutation
```

If a Profile has an active Session, Cookie import returns a structured busy error. The preview remains valid so the user may close the Session and retry without reparsing the file.

Profile archive now also acquires the mutation lease, preventing archive/import races.

## 7. ProfileMaintenanceHost

The Maintenance Host is:

- headless;
- bound to one explicit persistent Profile launch specification;
- launched only while the mutation lease is held;
- closed after one bounded maintenance operation;
- absent from Agent and Monitor routing;
- not registered as a BrowserSession.

Cookie import uses the browser-level CDP Storage domain:

```text
Storage.setCookies
Storage.getCookies
```

The implementation verifies imported Cookie identity internally, including value, but returns only the verified count. This prevents a false success result without exposing Cookie data.

The service reports only:

```text
cookies_imported
```

It deliberately does not report:

```text
login_restored
```

Website authentication must be verified later through normal page behavior.

## 8. Memory and Lifecycle

Raw normalized Cookies exist only in the in-memory pending preview record and the bounded CDP call.

They are removed when:

- the user cancels the preview;
- commit begins;
- the preview expires;
- the pending-preview cap evicts the oldest preview;
- Runtime shuts down.

A failed attempt to acquire the Profile lock does not consume the preview. Once mutation begins, the preview is single-use to avoid ambiguous replay after a partial write.

## 9. Control API

Protected endpoints:

```text
POST /v1/profiles/{profile_ref}/session/close
POST /v1/profiles/{profile_ref}/bootstrap/cookies/preview
POST /v1/profiles/{profile_ref}/bootstrap/cookies/cancel
POST /v1/profiles/{profile_ref}/bootstrap/cookies/import
```

The preview endpoint accepts raw bytes and the query parameters:

```text
expected_version
format=auto|json|netscape
```

The import endpoint accepts only the preview token and expected Profile version. Raw Cookies are not resent during commit.

## 10. Desktop Control UI

The Visualizer now includes a Profile Bootstrap panel with:

- persistent Profile selection;
- Cookie JSON / Netscape file selection;
- explicit target Session close;
- redacted preview;
- warning and scope summary;
- confirmation before write;
- cancel-and-clear action;
- import verification result.

The UI explicitly states that Cookie import does not prove login restoration.

## 11. Non-Creating Visualizer State

A maintenance-critical bug was found during implementation:

```text
closing the last Profile Session
  -> Visualizer poll
  -> compatibility observe path
  -> implicit default Session recreation
  -> Profile lock reacquired
```

`build_visualizer_state()` now obtains Supervisor status first. When the Supervisor has no active Session, it returns an inactive projection and does not call any compatibility method that creates a Runtime.

Regression coverage verifies:

```text
close Session
  -> poll Visualizer
  -> active_session_count remains 0
  -> ProfileMutationLease remains acquirable
  -> Cookie import succeeds
```

## 12. Tests

New and extended tests cover:

- JSON parsing;
- Netscape parsing;
- HttpOnly Netscape entries;
- host-only Cookie conversion;
- expired Cookie rejection;
- malformed input without secret echo;
- secret-free preview and result;
- control-session binding;
- preview cancellation;
- active Profile busy behavior and retry;
- Profile bootstrap-source update;
- protected two-phase API;
- Session close for maintenance;
- non-creating Visualizer polling;
- real Chromium import and persistence.

The real Chromium test imports a Cookie through the Maintenance Host, closes it, starts a normal Host with the same Profile, navigates to the target Origin, and verifies that the Cookie persisted.

## 13. Security Review

The implementation does not expose Cookie material through:

- MCP schemas;
- WebState or BrowserState;
- Monitor frames or events;
- SafetyReceipt;
- Profile runtime events;
- HTTP error responses;
- desktop UI previews;
- local resource grants.

Safe runtime events record only format, counts, domain count, verification count, and failure code.

## 14. External Protocol Basis

The implementation follows the Chromium DevTools Protocol definitions for:

- Storage domain `setCookies` / `getCookies`;
- Network domain `CookieParam`;
- Cookie partition keys.

These remain internal BrowserHost details and are not WebFA Agent capabilities.

## 15. Remaining Profile Bootstrap Work

Cookie import is complete. Remaining Post-Core Bootstrap work:

```text
Profile clone
WebFA Profile Bundle export/restore
maintenance verification workflows
optional browser-extension import adapters
```

Clone and bundle work must reuse `ProfileMutationLease` and must remain outside the Agent five-tool interface.
