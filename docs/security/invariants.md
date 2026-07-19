# WebFA Security Invariants

These rules define the current agent-native internet Runtime line. Historical
transaction/approval/proof code is legacy and must not shape the default agent
surface.

## Agent Surface

1. Default MCP tools are exactly `webfa.open_url`, `webfa.observe`,
   `webfa.act`, `webfa.get_tabs`, and `webfa.switch_tab`.
2. Raw Playwright, raw CDP, raw DevTools, selectors, XPath, and arbitrary
   evaluate are not public agent capabilities.
3. Site-specific business APIs are not public agent capabilities.
4. Page operations remain under `webfa.act`; new public tools require an
   explicit resource-domain decision.

## Browser State

5. Neither current `WebState`/WebObjects nor the disabled legacy `BrowserState`
   may include cookies, localStorage, sessionStorage, IndexedDB values,
   authorization headers, tokens, password values, full DOM, or full HTML.
6. Agent-visible state may include URL parts, visible text, structured content,
   forms, WebObjects, capabilities, versions, changes, tabs, auth/takeover state,
   and safe Agent/Profile/Session lease metadata.
7. Credential fields may be represented as protected or opaque surfaces, but
   their values must never be exposed and Agents must not fill them. Credential
   entry belongs to the local HumanControl path.
8. Tab and WebObject identities bind Session, Runtime generation, document
   identity/revision, and object version as required. Navigation invalidates
   document-bound references; raw selectors and engine handles never substitute
   for those identities.
9. Agent-visible safety evidence may expose URL class, policy, and risk flags,
   but must not expose cookies, storage, tokens, or credential material. URL
   policy in P9.2 is developer-preview lightweight classification only; it is
   not a complete SSRF or internal-network firewall (no DNS resolution and known
   literal bypass gaps).
10. Dialog WebObjects may expose dialog identity, type, message, and whether
    user action is required, but must not expose arbitrary page script state.
11. Frame metadata or content may be exposed only under the current origin and
    opaque-surface rules; cross-origin frame contents must not leak into Agent-
    visible text or objects.
12. Structured runtime errors must use `{code, message, recover_hint}` and must
    not include stack traces, CDP payloads, or internal host details.

## Authentication

13. Human login, QR, 2FA, verification, and authorization takeover uses the
    Session Monitor projection of the same BrowserHost page under a
    time-bounded, Session-scoped `HumanControlLease`. The retired duplicate-page
    Electron AuthSurface must not be recreated.
14. Agents must not ask users for passwords, verification codes, cookies,
    storage values, or tokens in chat.
15. HumanControl input must use the existing page target and Profile without
    exposing credential material, input values, cookies, or storage to MCP,
    Agent REST responses, events, logs, receipts, or docs. Keyboard capture must
    provide an Escape path back to visible Monitor controls without silently
    releasing the lease, and an active lease must remain explicitly releasable
    while connected even when a visual frame is temporarily unavailable.
16. A HumanControlLease binds the authenticated Monitor connection, Profile,
    Session, active tab, Runtime generation, and expiry. It pauses Agent writes
    only in that Session and ends on release, expiry, revocation, disconnect, or
    Monitor closure. Takeover must not close/restart BrowserHost or create a
    second page.

## Agent Coordination

17. One Runtime may host multiple persistent Profiles and Sessions. Each
    persistent Profile has an isolated Chromium identity and at most one active
    writable BrowserSession and Managed Chromium Host; different Profiles may
    run concurrently.
18. An Agent Profile Grant is bound to Agent and connection identity, Profile
    policy, and expiry. Versioned Profile policy metadata remains live while a
    Session exists so the protected control plane can revoke or narrow access;
    continued Agent activity must re-read that policy and fail closed when its
    binding no longer matches. This Catalog update is not browser-storage
    maintenance and must not be coupled to `ProfileMutationLease`. The exclusive
    Agent Session Lease additionally binds Profile, Session, and Runtime
    generation; a second connection must not write the same active Profile
    Session, and the Session itself must never switch to another Profile.
19. Tab and WebObject references, Monitor grants, HumanControlLease, and P11
    authority must fail closed across Profile, Session, connection, or Runtime-
    generation boundaries. Read-only state may expose safe lease/identity
    metadata, but never Profile internals or credentials.

## Runtime Boundary

20. The Python Runtime owns WebState/WebObject generation, Profile and Session
    lifecycle, BrowserHost descendants, grants and leases, HumanControl state,
    and safety checks.
21. MCP is a protocol adapter only. It does not write DB state, bypass leases,
    create hidden capabilities, or call browser protocols directly.
22. Electron and future visualizers are optional observation/takeover surfaces;
    they must not become the core agent interface. A separately authenticated
    control operation may create or resolve Session-scoped management state,
    but it must not impersonate an Agent, mint an Agent Profile Grant or Session
    write lease, or execute a webpage decision.
23. The unauthenticated loopback `/health` response may expose bounded product,
    version, instance, capability, lease, and storage-readiness metadata, but it
    must not expose absolute data, database, log, Profile, or browser-storage
    paths. Explicit local diagnostics such as `webfa paths` own path disclosure.
    Process launch and startup failures similarly cross the Renderer boundary as
    bounded issue codes and recovery actions; raw child errors, stderr, paths,
    and tracebacks remain in local application logs.
24. SQLite foreign keys must be enabled on every Runtime connection. Migration
    milestones and their required seed rows commit atomically after additive
    schema creation. Local Provider credential references must not escape the
    credential root, credential replacement must be atomic, and failed
    credential/metadata lifecycle operations must restore their prior coherent
    state without exposing the token.
25. Profile archive and restore must hold the same OS-backed mutation lock used
    by offline bootstrap work before changing Catalog state. Cookie, clone,
    Bundle, deletion, migration, and other browser-storage maintenance must not
    overlap an active Session; ordinary optimistic-versioned Profile policy
    metadata updates are intentionally outside this filesystem lease. Managed Profile
    roots and their direct user-data/download/maintenance directories must not
    be symbolic links or directory junctions, and Profile IDs must not carry
    path or drive syntax.

## Legacy Isolation

26. Historical transaction tools remain disabled unless
    `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
27. Legacy provider, approval, proof, and audit code must not appear in the
    default MCP tool list.
28. Legacy docs must be marked as historical or abandoned when they describe
    behavior outside the current agent-browser runtime line.

## Release Hygiene

29. Public docs must not contain local filesystem paths, personal account names,
    screenshots from private sessions, raw credentials, or private test data.
30. Build artifacts, virtual environments, local reports, and generated scratch
    specs must not be committed.
31. Before a developer-preview release, run the checklist in
    `RELEASE_CHECKLIST.md`.
