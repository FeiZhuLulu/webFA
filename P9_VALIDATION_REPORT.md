# P9 WebFA Visualizer MVP Validation Report

Date: 2026-07-04

## Status

P9 Visualizer MVP has been integrated at the code level and passed the automated validation gate.

Manual auth-takeover validation against real login/QR sites is still listed as a product smoke test because it requires user interaction and a live site. P9.1 changes the expected behavior: authentication should appear in the WebFA-owned takeover area, not an external Chromium window.

## Implemented

Backend:

- `GET /v1/visualizer/state`
- `POST /v1/visualizer/restart-host`
- `POST /v1/visualizer/open-auth-surface`
- `POST /v1/visualizer/open-host` compatibility wrapper
- In-memory recent action log
- Screenshot preview with short server-side cache
- BrowserRuntime preview/restart/auth-surface hooks

Frontend:

- Three-column Visualizer shell
- Runtime status panel
- Human control panel
- Page preview panel
- Auth takeover and host-closed banner
- Tabs display
- Agent View element table
- Content blocks list
- Action log
- Expandable BrowserState JSON

Security hardening added during Codex review:

- Action log redacts sensitive URL query parameters and plain message values.
- Visualizer state now samples browser status after observe, so runtime status and page state are consistent.
- Existing MCP five-tool contract remains unchanged.

## Automated Validation

Targeted validation:

```text
python -m pytest tests/unit/test_action_log.py tests/unit/test_preview_cache.py tests/integration/test_visualizer_api.py tests/contract/test_visualizer_security_contract.py tests/contract/test_mcp_security_contract.py -q
```

Result:

```text
22 passed
```

Full-suite validation:

```text
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Result:

```text
python -m pytest -q          -> 231 passed, 2 warnings
npm run typecheck:renderer   -> passed
npm run typecheck:electron   -> passed
python -m build              -> passed
```

## Boundary Review

Passed:

- Visualizer does not add MCP tools.
- Visualizer does not expose raw Playwright, raw CDP, DevTools console, selectors, XPath, or evaluate.
- Visualizer UI is an inspector/takeover panel, not a traditional browser UI.
- Visualizer controls are limited to refresh, open WebFA takeover area, restart host, copy BrowserState JSON, and desktop Runtime start/stop.
- Screenshot preview is not exposed through MCP.
- Sensitive values are not intentionally exposed through BrowserState or action logs.

Known limits:

- Screenshot preview can visually contain whatever is on the user's current page. This is acceptable for local Visualizer use but should not become an MCP tool or remote API surface.
- Element highlight overlay is not implemented yet.
- Tabs are shown read-only; switching remains available through existing agent/browser APIs but is not productized in the Visualizer UI.
- Real login/QR validation still needs a user-assisted smoke test.
- P9.1 requires the takeover page to render inside the WebFA UI and use the same default profile as Runtime.

## Manual Smoke Checklist

Use this before marking P9 fully accepted:

- [ ] Open `http://127.0.0.1:8788` and confirm Visualizer loads.
- [ ] Use an external agent to open `https://example.com`; confirm URL/title/preview/action log update.
- [ ] Use the validation fixture to type `Fei` and submit; confirm `Hello Fei` appears in BrowserState/log.
- [ ] Open an already logged-in GitHub page; confirm Visualizer shows logged-in page state without exposing credentials.
- [ ] Open a login/QR/verification page; confirm the login UI appears in the WebFA takeover area, not an external Chromium window.
- [ ] Complete/cancel takeover; confirm `webfa.observe` works again with the same default profile.

## Decision

P9 is ready for user-assisted manual smoke testing. Automated validation has passed. The remaining manual item is real auth/QR validation, because it requires a live site and user interaction.

Suggested commit:

```text
feat: add WebFA Visualizer MVP
```
