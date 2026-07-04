# WebFA Security Invariants

These rules define the current agent-browser runtime line. Historical
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

5. `BrowserState` must not include cookies, localStorage, sessionStorage,
   IndexedDB values, authorization headers, tokens, password values, full DOM,
   or full HTML.
6. `BrowserState` may include URL parts, visible text, content blocks, forms,
   elements, tabs, auth status, and active agent/profile metadata.
7. Password fields may be reported as fields, but password values must be empty
   and agents must not fill them.
8. Element ids are page-state references, not stable cross-navigation
   identities. Navigation or host restart invalidates old ids.
9. `BrowserState.security` may expose URL class, policy, and risk flags, but
   must not expose cookies, storage, tokens, or credential material. URL policy
   in P9.2 is developer-preview lightweight classification only; it is not a
   complete SSRF or internal-network firewall (no DNS resolution, known literal
   bypass gaps).
10. `BrowserState.dialogs` may expose dialog id, type, message, and whether
    user action is required, but must not expose arbitrary page script state.
11. `BrowserState.frames` may expose frame metadata for same-origin frames only;
    cross-origin frame contents must not leak into agent-visible text or elements.
12. Structured runtime errors must use `{code, message, recover_hint}` and must
    not include stack traces, CDP payloads, or internal host details.

## Authentication

13. WebFA uses the WebFA-owned Auth Surface for human login, QR, 2FA, or
   authorization. A separate visible host is legacy fallback only.
14. Agents must not ask users for passwords, verification codes, cookies,
    storage values, or tokens in chat.
15. Auth takeover must use the same local profile without exposing credential
    material to MCP, REST responses, logs, or docs.
16. Opening Auth Surface releases the hidden Runtime host while takeover is
    active. Completing/canceling takeover restarts the host with the same
    profile, but page memory and old element ids are lost.

## Agent Coordination

17. The developer-preview default is one Runtime, one default session, one
    default shared profile, and one active mutating agent lease.
18. Browser-changing calls from another agent during an active lease must return
    `agent_busy`.
19. Read-only state may expose the active agent id and shared profile metadata,
    but never profile internals or credentials.

## Runtime Boundary

20. The Python Runtime owns BrowserState generation, element registry, profile
    use, auth takeover, leases, and safety checks.
21. MCP is a protocol adapter only. It does not write DB state, bypass leases,
    create hidden capabilities, or call browser protocols directly.
22. Electron and future visualizers are optional observation/takeover surfaces;
    they must not become the core agent interface.

## Legacy Isolation

23. Historical transaction tools remain disabled unless
    `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
24. Legacy provider, approval, proof, and audit code must not appear in the
    default MCP tool list.
25. Legacy docs must be marked as historical or abandoned when they describe
    behavior outside the current agent-browser runtime line.

## Release Hygiene

26. Public docs must not contain local filesystem paths, personal account names,
    screenshots from private sessions, raw credentials, or private test data.
27. Build artifacts, virtual environments, local reports, and generated scratch
    specs must not be committed.
28. Before a developer-preview release, run the checklist in
    `RELEASE_CHECKLIST.md`.
