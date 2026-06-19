# P5 Browser Runtime Core Freeze

Date: 2026-06-19

## Status

P5 is frozen as the current browser runtime core baseline.

P5 kept the public WebFA browser interface unchanged:

```text
REST: /v1/browser/open, observe, act, tabs, tabs/switch
MCP:  webfa.open_url, webfa.observe, webfa.act, webfa.get_tabs, webfa.switch_tab
```

## Commits

```text
df03d36 chore: freeze p4.6 browser runtime baseline
094d40e refactor: isolate browser driver boundary
f95ab83 refactor: build browser state from agent view
405b92b refactor: track browser element ids in registry
a77cb81 refactor: introduce default browser session
7ff9ed9 docs: mark browser runtime core roadmap
```

## Result

- `BrowserRuntime` no longer directly owns Playwright page/context code.
- Playwright-specific logic is isolated in `PlaywrightBrowserDriver`.
- `RawPageSnapshot` is the boundary between driver facts and WebFA state.
- `AgentViewBuilder` builds `BrowserState`.
- `ElementRegistry` owns current-page element id validity.
- `BrowserSession` establishes the default session/profile skeleton.
- Default MCP tools remain exactly the five browser tools.

## Verification

```text
pytest -q
131 passed, 7 skipped, 2 warnings

npm run typecheck:renderer
passed

npm run typecheck:electron
passed
```

The two pytest warnings are dependency deprecation warnings from `websockets` / `uvicorn`.

## Frozen Constraints

- No raw Playwright, raw CDP, selector, XPath, locator, or evaluate tools are exposed.
- No site business tools are exposed by default.
- Legacy transaction tools remain gated behind `WEBFA_ENABLE_LEGACY_TRANSACTION=1`.
- `BrowserState` must not expose cookies, storage, tokens, full DOM, or full HTML.
- `webfa.open_url` and REST open still return updated `BrowserState`.
- P4.6 URL-first behavior remains valid.

## Known Leftover

`tests/integration/test_github_pr_live.py` remains an untracked legacy GitHub PR transaction residue and is not part of the P5 baseline.

## Next Candidate

P6 should focus on WebFA Visualizer / headless runtime shape, not on replacing Playwright yet.
