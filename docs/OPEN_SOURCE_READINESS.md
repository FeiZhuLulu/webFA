# Open Source Readiness

P8.11 keeps WebFA ready for a developer-preview open source release after the
agent integration hardening and visible-host stability work.

## Release Positioning

WebFA should be published as a developer preview, not a stable end-user
browser. The README, security policy, and roadmap should make these boundaries
clear:

- agent-native browser runtime
- local MCP-first integration
- one default shared profile
- one active agent lease
- managed Chromium as the current runtime host
- no anti-bot bypass
- no high-risk action confirmation layer yet

## Public Entry Points

- `webfa-runtime`
- `webfa-mcp`
- `webfa mcp-config`
- `webfa doctor`
- `webfa login`

Default MCP tools remain:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

## Files Added for Open Source

- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `.env.example`
- `docs/agent-integrations/*.md`

## Hygiene Checks

- Root README explains developer-preview status and current limits.
- Personal local paths and account names were removed from public validation
  reports.
- Local login test reports are ignored by `.gitignore`.
- Local Superpowers planning drafts are ignored by `.gitignore`.
- Local Runtime HTTP calls bypass system proxy environment variables for
  loopback URLs, so MCP clients are not broken by user-level SOCKS proxies.
- Security policy states that credentials, cookies, storage, tokens, passwords,
  raw CDP, raw Playwright, selectors, XPath, and full DOM/HTML must not be
  exposed to agents.
- Historical GitHub/provider transaction docs are marked as legacy or abandoned.

## Verification

Run before publishing:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Use `RELEASE_CHECKLIST.md` for the full publish gate.
