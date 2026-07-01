# WebFA Developer Preview Release Checklist

Use this checklist before publishing a developer-preview release.

## Positioning

- [ ] README says WebFA is an agent-native browser runtime, not a traditional
  browser, DevTools wrapper, site API wrapper, or autonomous agent.
- [ ] Current limits are visible: shared default profile, one active agent,
  no anti-bot bypass, no multi-profile isolation, no high-risk confirmation
  layer yet.
- [ ] Roadmap points to P9 Visualizer, P10 Element Registry v2, P11 multi
  profile/session, and P12 safety confirmation.

## Agent Interface

- [ ] Default MCP tool list is exactly:
  `webfa.open_url`, `webfa.observe`, `webfa.act`, `webfa.get_tabs`,
  `webfa.switch_tab`.
- [ ] Legacy transaction tools appear only with
  `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
- [ ] No public docs instruct agents to use raw Playwright, CDP, DevTools,
  selectors, XPath, evaluate, cookies, storage, tokens, or site APIs.
- [ ] `AGENT_MANUAL.md` matches current BrowserState and action semantics.

## Install And Entry Points

- [ ] Fresh venv install works with `pip install -e ".[dev]"`.
- [ ] `webfa-runtime` starts Runtime.
- [ ] `webfa-mcp` reuses or auto-starts Runtime.
- [ ] `webfa mcp-config --agent-id <agent>` emits usable config.
- [ ] `webfa mcp-config --client opencode --agent-id opencode` emits opencode
  config.
- [ ] `webfa doctor` completes on a machine with a Chromium executable.
- [ ] Local Runtime calls bypass system proxy env vars for loopback URLs.

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
one low-risk authenticated page already logged into the default profile
```
