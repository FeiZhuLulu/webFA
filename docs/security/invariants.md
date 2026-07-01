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

## Authentication

9. WebFA may open a visible managed Chromium host for human login, QR, 2FA, or
   authorization.
10. Agents must not ask users for passwords, verification codes, cookies,
    storage values, or tokens in chat.
11. Auth takeover must use the same local profile without exposing credential
    material to MCP, REST responses, logs, or docs.
12. Closing the visible host ends the current browser host. `open_url` may
    restart it with the same profile, but page memory and old element ids are
    lost.

## Agent Coordination

13. The developer-preview default is one Runtime, one default session, one
    default shared profile, and one active mutating agent lease.
14. Browser-changing calls from another agent during an active lease must return
    `agent_busy`.
15. Read-only state may expose the active agent id and shared profile metadata,
    but never profile internals or credentials.

## Runtime Boundary

16. The Python Runtime owns BrowserState generation, element registry, profile
    use, auth takeover, leases, and safety checks.
17. MCP is a protocol adapter only. It does not write DB state, bypass leases,
    create hidden capabilities, or call browser protocols directly.
18. Electron and future visualizers are optional observation/takeover surfaces;
    they must not become the core agent interface.

## Legacy Isolation

19. Historical transaction tools remain disabled unless
    `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
20. Legacy provider, approval, proof, and audit code must not appear in the
    default MCP tool list.
21. Legacy docs must be marked as historical or abandoned when they describe
    behavior outside the current agent-browser runtime line.

## Release Hygiene

22. Public docs must not contain local filesystem paths, personal account names,
    screenshots from private sessions, raw credentials, or private test data.
23. Build artifacts, virtual environments, local reports, and generated scratch
    specs must not be committed.
24. Before a developer-preview release, run the checklist in
    `RELEASE_CHECKLIST.md`.
