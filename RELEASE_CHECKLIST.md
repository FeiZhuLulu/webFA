# WebFA Developer Preview Release Checklist

Use this checklist before publishing a developer-preview release.

## Positioning

- [ ] README says WebFA is an agent-native browser runtime, not a traditional
  browser, DevTools wrapper, site API wrapper, or autonomous agent.
- [ ] Current limits are visible: one active Browser Profile, one active Agent,
  no anti-bot bypass, no P12 multi-profile isolation, session-local resource,
  policy, step-up, and receipt state, no durable P13 restoration, and no local
  raw-card Vault.
- [ ] Roadmap records P10 and P11.0-P11.10 complete and points to P12
  multi-session/profile and P13 durable trace/resume.
- [ ] If Visualizer is included, docs state that it is an inspector/takeover
  panel, not a traditional browser UI.

## Agent Interface

- [ ] Default MCP tool list is exactly:
  `webfa.open_url`, `webfa.observe`, `webfa.act`, `webfa.get_tabs`,
  `webfa.switch_tab`.
- [ ] Legacy transaction tools appear only with
  `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
- [ ] No public docs instruct agents to use raw Playwright, CDP, DevTools,
  selectors, XPath, evaluate, cookies, storage, tokens, or site APIs.
- [ ] `AGENT_MANUAL.md` documents WebState, WebObjects, queryable observe,
  semantic operations, versions, ChangeSets, SafetyContext, Runtime evidence,
  Profile ownership/binding, opaque resource upload, protected payment instruments,
  exact-scope step-up, SafetyReceipt audit, protected inputs, and takeover as the
  default MCP protocol.
- [ ] BrowserState/BrowserAction REST compatibility is isolated under the
  explicit `/v1/browser/legacy/*` namespace; hidden old aliases are not in
  OpenAPI, neither path is used by MCP, and all Legacy endpoints return
  `410 legacy_browser_api_disabled` unless the explicitly unsafe historical-test
  switch `WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API=1` is set.
- [ ] Python package metadata has no Playwright dependency and Managed Chromium
  is the only accepted BrowserHost path.
- [ ] PaymentInstrumentRef contains opaque identifiers and safe display metadata
  only; PAN, CVV, payment password, OTP, and wallet-token fields are absent.
- [ ] Payment option selection does not consume financial usage; the final
  submit/pay control rechecks amount, currency, limits, active document, and the
  exact selected instrument before recording usage. One-click payment controls
  are classified as final commits before activation.
- [ ] Step-up grants bind exact navigation URL fingerprints or WebObject
  document identity/version, are single-use, and never expose human decision
  notes to Agent responses.
- [ ] File upload accepts scoped `resource_ref` only; arbitrary local paths are
  absent from Agent-visible requests, responses, logs, and receipts.

## Install And Entry Points

- [ ] Fresh venv install works with `pip install -e ".[dev]"`.
- [ ] `webfa-runtime` starts Runtime.
- [ ] `webfa-mcp` reuses or auto-starts Runtime.
- [ ] `webfa mcp-config --agent-id <agent>` emits usable config.
- [ ] `webfa mcp-config --client opencode --agent-id opencode` emits opencode
  config.
- [ ] `webfa doctor` completes on a machine with a Chromium executable.
- [ ] Local Runtime calls bypass system proxy env vars for loopback URLs.
- [ ] Formal Web operations are serialized across safety evaluation, browser
  execution, financial accounting, and receipt creation.
- [ ] Complete Visualizer development entry works with `npm run dev`; Electron
  starts the token-bound Runtime. `npm run dev:renderer` alone is not documented
  as a complete control-plane entry.
- [ ] Every `/v1/visualizer/*` route requires `X-WebFA-Visualizer-Token`; Electron
  generates it at runtime, locks navigation and IPC to the local Console, and no
  `NEXT_PUBLIC` build variable contains the token.

## Repository Hygiene

- [ ] `git status --short` is clean except intentionally ignored local files.
- [ ] `.gitignore` excludes local reports, virtualenvs, build artifacts,
  `.tmp/`, and `docs/superpowers/`.
- [ ] Public docs contain no personal filesystem paths, user account names,
  private screenshots, credentials, or generated clipboard artifacts.
- [ ] Historical transaction/provider material is in `docs/abandoned/`,
  marked legacy, or absent from the default public path.
- [ ] Build artifacts under `dist/`, `.pytest_cache/`, `.next/`, and local DB
  files are not committed.

## Verification

Run these commands before tagging:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Manual smoke:

```text
external agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

Recommended pages:

```text
https://example.com
tests/fixtures/agent_validation_page.html
tests/fixtures/p11_safety_page.html
one low-risk authenticated page already logged into the default profile
```
