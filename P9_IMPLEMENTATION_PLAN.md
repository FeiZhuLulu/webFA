# P9 WebFA Visualizer MVP Implementation Plan

## Summary

P9 adds a WebFA Visualizer MVP: a local runtime inspector and human takeover panel for WebFA.

It does not change the agent-facing MCP surface. Default MCP tools remain:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

The Visualizer is for humans to observe runtime state, inspect agent-readable page state, see recent actions, and recover or open the visible host when human authentication is required. It is not a traditional browser UI and not a general human browsing product.

## Scope

P9 includes:

- `GET /v1/visualizer/state`
- `POST /v1/visualizer/restart-host`
- `POST /v1/visualizer/open-host`
- In-memory visualizer action log
- Cached screenshot preview for the local Visualizer
- Electron/Next renderer three-column Visualizer UI
- Runtime, page, Agent View, content blocks, action log, auth takeover, and host-closed display
- Contract tests for MCP tool stability and sensitive-field boundaries

P9 does not include:

- New MCP tools
- Address bar or traditional browser chrome
- Bookmarks/history/download manager
- Site-specific parsers or business actions
- Anti-bot, CAPTCHA bypass, proxy, or stealth features
- Raw Playwright/CDP/selector/XPath/evaluate access
- Multi-session or multi-profile UI
- High-risk final-action confirmation

## Architecture

```text
External Agent
  -> MCP five browser tools
  -> Runtime Browser API
  -> Browser Runtime
  -> Browser Host / Engine

Human Operator
  -> WebFA Visualizer
  -> /v1/visualizer/state
  -> Runtime status + BrowserState + preview + action log
```

The Visualizer reads the same WebFA state that agents use, plus local-only operator metadata. It must not become a separate browser automation API.

## Runtime API

### `GET /v1/visualizer/state`

Returns a structured `VisualizerState`:

- `runtime`: driver, host status, headless/visible state
- `agent`: active agent lease
- `profile`: default shared profile metadata
- `page`: URL, title, page status, auth state
- `browser_state`: current sanitized `BrowserState`, if available
- `preview`: cached PNG data URL for visual observation
- `recent_actions`: recent browser/visualizer calls with sensitive values redacted
- `errors`: current visualizer/runtime errors

### `POST /v1/visualizer/restart-host`

Restarts the current browser host with the current URL when possible. This is a human recovery control. It clears the screenshot cache and invalidates old element ids through the existing runtime restart semantics.

### `POST /v1/visualizer/open-host`

Relaunches the visible managed host for human takeover. This is used for login, QR, verification, 2FA, or authorization flows. It does not expose credentials to agents or the Visualizer API.

## Frontend

The renderer uses the approved three-column "command center" layout:

- Left: Runtime status and controls
- Center: page preview, URL/title/status, tabs, auth takeover/host closed banner
- Right: Agent View, content blocks, action log, BrowserState JSON

The UI is intentionally a Runtime Inspector and Human Takeover Panel. It should not look or behave like Chrome, Edge, or a normal browser.

## Security Boundaries

P9 must preserve these invariants:

- No new default MCP tools.
- No raw Playwright, CDP, DevTools, selector, XPath, locator, or evaluate surface.
- `BrowserState` and `VisualizerState` must not expose cookies, localStorage/sessionStorage values, tokens, authorization headers, password values, full DOM, or full HTML.
- Action log messages must redact sensitive query parameters such as `token`, `access_token`, `code`, `password`, `secret`, `authorization`, and `credential`.
- Screenshot preview is local Visualizer-only. It is not exposed as an MCP tool.
- Historical transaction/provider tools remain legacy and disabled by default.

## Validation Plan

Automated:

```powershell
python -m pytest tests/unit/test_action_log.py tests/unit/test_preview_cache.py tests/integration/test_visualizer_api.py tests/contract/test_visualizer_security_contract.py -q
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Manual:

```text
1. Start Runtime and Visualizer.
2. Use an external agent to open https://example.com.
3. Verify Visualizer shows URL, title, preview, BrowserState, and action log.
4. Use the local validation fixture and submit "Fei"; verify state/log update.
5. Open a logged-in GitHub page; verify profile state and page state display.
6. Open a login/QR/verification site; verify auth takeover banner and visible host guidance.
7. Close the visible host; verify browser_host_closed display and restart guidance.
```

## Acceptance Criteria

P9 is accepted when:

- Visualizer API returns usable state without adding MCP tools.
- Visualizer UI displays runtime/page/agent/log information from real Runtime state.
- The UI is clearly an inspector/takeover panel, not a traditional browser.
- Sensitive values are not exposed in state, logs, or MCP responses.
- Action log redacts sensitive URL/query values.
- Full test and typecheck suite pass.
- Manual smoke tests are recorded in `P9_VALIDATION_REPORT.md`.
