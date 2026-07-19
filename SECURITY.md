# Security Policy

WebFA is a local agent-native internet Runtime. It can operate real websites
with persistent login state, so a defect may affect online accounts and real
external state even though the Runtime is local.

## Supported status

Current status: developer preview.

WebFA is not yet a stable production browser, password manager, remote browser
service, or unattended high-risk automation platform. Do not expose Runtime or
MCP directly to an untrusted network. Do not use it unattended for banking,
payments, account recovery, destructive administration, sensitive mailbox
workflows, or other high-consequence writes.

## Reporting issues

Do not publish exploit details, secrets, or private website content in a public
issue. Open a minimal issue stating that you have a security concern and include
a non-sensitive contact method. Do not attach tokens, cookies, passwords,
one-time codes, Profile Bundles or passphrases, browser storage, authorization
headers, local paths, or screenshots containing private information.

## Trust and deployment boundary

- Runtime and MCP are designed for loopback/local deployment. Agent identity is
  a local protocol claim, not a cryptographically authenticated remote
  principal.
- The human control plane uses a separate high-entropy token. Electron creates
  a fresh token for each Runtime it owns, passes it only to the validated local
  Renderer, and clears it when ownership ends.
- Desktop does not adopt control authority over a compatible external Runtime
  and never stops a Runtime or MCP process it did not start.
- MCP stdio belongs to the external Agent client. MCP auto-start is loopback
  only, validates exact Runtime identity, coordinates clients with leases, and
  stops only its own Runtime after the last live client exits.

## Profile, Session, and lease boundaries

WebFA implements multiple persistent internet identities and multiple concurrent
Sessions with these boundaries:

- A `BrowserProfile` owns one isolated Chromium user-data directory and durable
  website identity state. Different Profiles may run concurrently.
- One persistent Profile may have at most one active writable BrowserSession and
  one Managed Chromium Host. An OS-backed Profile process lock prevents a second
  process from opening the same Profile data concurrently.
- Offline Cookie import, clone, Bundle restore, deletion, and other Profile
  maintenance require a separate Profile mutation lease and cannot overlap an
  active Profile Session. Archive and soft-restore also acquire that lock before
  changing Catalog state; a busy Profile remains unchanged.
- Versioned Profile policy metadata is not browser-storage maintenance. The
  protected control plane may narrow Agent bindings or Origin scope while a
  Session exists, and continued Agent operations recheck the current policy so
  revocation takes effect without restarting the BrowserHost. The Session stays
  bound to the same Profile throughout.
- Profile IDs cannot contain path separators or drive/alternate-stream syntax.
  The managed Profile root, Chromium user-data directory, downloads directory,
  and maintenance directory reject symbolic links and directory junctions
  before WebFA creates or uses them.
- An Agent Profile Grant is bound to Agent and connection identity, Profile
  policy, and expiry. It exposes an opaque `profile_ref`, never a storage path.
- An Agent Session Lease is exclusive and binds Agent ID, connection ID,
  Profile ID, Session ID, runtime generation, and expiry. A second connection
  cannot write the same active Profile Session; different Profile Sessions can
  remain concurrent.
- Global Tab and WebObject references bind their Session and runtime generation.
  Cross-Session use and stale-generation replay fail before page execution.
- A Monitor Grant is one-time/expiring and binds the exact Profile, Session,
  runtime generation, and permissions. HumanControlLease is Session-local;
  takeover pauses Agent writes only in that Session and is released on expiry,
  revocation, disconnect, or Monitor closure.

## Safety and exact-scope authorization

P11 safety enforcement is implemented; it is not merely a planned confirmation
layer. Semantic writes are evaluated against Runtime evidence, Profile policy,
SafetyContext, and deterministic hard boundaries before execution.

- Step-up grants are connection-, Profile-, Session-, and generation-scoped.
  They bind the exact navigation URL fingerprint or document identity/version,
  target object, operation, and approved scope; approved grants are single-use
  by default.
- A mismatch does not consume or broaden the original grant. Expired, rejected,
  consumed, cross-connection, cross-document, cross-Profile, cross-Session, and
  stale-generation use fails closed.
- LocalResourceGrant and payment authority use the same scoped model. Resource
  paths, raw card data, CVV, payment passwords, OTPs, wallet tokens, and human
  decision notes are not exposed to Agents.
- Known external writes and form-submit activation are promoted to safety
  dimensions such as `unknown_external_effect`. User-owned Profiles default to
  requiring step-up for unknown effects; policy may allow audited autonomy for
  explicitly configured Agent-owned identities.

This enforcement does not make all websites safe. `open_url` and link `open`
are navigation semantics. A site can violate HTTP conventions and perform an
external write in response to an apparently read-only GET navigation. WebFA
cannot reliably infer that hidden business side effect from the URL or HTTP
method alone. Supervise unfamiliar navigation and any operation whose external
effect is unknown, especially on user-owned or high-value accounts; do not
interpret a GET request as proof that no side effect occurred.

## Secret and Agent-visible data boundary

The default Agent protocol must not expose:

- cookies or localStorage/sessionStorage/IndexedDB values;
- passwords, one-time codes, authorization headers, or account tokens;
- raw card numbers, CVV, payment passwords, or wallet tokens;
- Profile Bundle passphrases or decrypted Bundle contents;
- local filesystem or Chromium Profile paths;
- raw Chrome DevTools Protocol, Playwright handles, selectors, XPath, evaluate,
  full DOM, or full HTML;
- unredacted human input or private Monitor control data.

Authentication, QR codes, verification codes, 2FA, payment verification, and
other protected inputs should use the human takeover surface. Agents receive
only bounded state and safe outcomes.

Profile Bootstrap is a protected local-control-plane capability. Cookie import
uses redacted preview and validation; clone and encrypted `.webfa-profile`
Bundle operations deliberately exclude passwords/autofill, history, bookmarks,
open tabs, extensions, and other Chrome Profile material outside the accepted
identity-state subset. Restoring browser storage does not guarantee that a site
will accept the restored login.

## Restart and durability boundary

Persistent Profile browser storage survives a normal Runtime restart. Active
Session execution state and authority do not: Profile/Monitor grants, Agent and
HumanControl leases, SafetyContext, Step-up, resource/payment state, and task
progress are invalidated, and stale active Sessions become `interrupted`.

P13 Durable Trace / Resume is explicitly deferred. WebFA does not currently
promise crash-safe task replay, page restoration, or continuation of an
in-flight external write. After a crash or ambiguous network/browser failure,
inspect the real website state before retrying to avoid duplicate effects.

## Additional developer-preview limitations

- Some websites block or behave differently in automated browser environments;
  WebFA does not bypass CAPTCHA, anti-bot, fraud, or platform security controls.
- Native permission prompts, OS file pickers, hardware security keys, and
  secure-attention flows do not yet share one complete agent-native abstraction.
- Persistent Profiles use a dedicated Chromium process each; resource limits
  and host availability still require operator monitoring.
- Enabling `WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1` deliberately restores
  primitive historical calls and voids the normal P10/P11 guarantees for those
  requests.
- A formal Windows distribution additionally requires a stable application
  identity/icon, signed and timestamped artifacts, and installed-artifact UI and
  lifecycle acceptance. See `RELEASE_CHECKLIST.md`.
