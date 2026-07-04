# P9.2 Runtime Safety Report (Developer Preview)

**Status:** Shipped for developer preview — not production-grade network isolation.

## Scope

P9.2 adds structured runtime errors, lightweight URL policy, JavaScript dialog MVP,
same-origin iframe metadata, and Agent View hardening. MCP remains five tools; no
raw CDP, selector, or evaluate surface was added.

**Driver policy:** Managed Chromium is the complete P9.2 path. Playwright
(`WEBFA_BROWSER_DRIVER=playwright`) is a fallback for basic open/observe/act only.
Dialog, frame, and URL-policy parity on Playwright is explicitly out of scope.

## Delivered

- `BrowserState.security`, `dialogs`, `frames`; structured `error`
- `WEBFA_PRIVATE_URL_POLICY` (allow / warn / block)
- `accept_dialog` / `dismiss_dialog` via `webfa.act` (managed Chromium)
- Same-origin iframe elements with `frame_id`; cross-origin metadata only
- Docs: `AGENT_MANUAL.md`, `invariants.md`, `browser-runtime-roadmap.md`

## Known limitations (documented, not hidden)

| Area | Limitation |
|------|------------|
| URL policy | Hostname-string classification only; no DNS resolution; non-standard IP literals may bypass `block` |
| CDP | `--remote-allow-origins=*` acceptable for dev; tighten before public release |
| Dialog MVP | `alert`/`confirm` on managed Chromium; `prompt` text input not supported; slow dialogs may be missed |
| Frames | Top-level iframes only; nested iframes not supported |
| Playwright | No dialog/frame URL-policy parity required |

## Follow-up (P9.3+)

- DNS-aware / resolved-IP URL policy
- `accept_dialog` + `prompt_text`
- Tighten CDP remote origins
- Optional: remove `__webfaPendingDialog` test shim from production observe path

## Validation

```text
Focused P9.2 suite: 37+ passed (url policy, runtime errors, dialog schema, P9.2 integration, MCP security contract)
Full pytest -q: 266 passed
typecheck:electron, typecheck:renderer, build:electron, python -m build: pass
```

## Positioning

Use **P9.2 Developer Preview hardening** in release notes. Do not describe this
phase as production-grade SSRF or internal-network isolation.