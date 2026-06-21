# P8.6 Automatic Auth Takeover UI Report

## Goal

P8.6 moves login handling into the normal WebFA Runtime path. Agents should not
call a special login tool. If a page looks like a login, QR-code,
verification-code, 2FA, or authorization surface, WebFA automatically opens the
same page in a visible managed Chromium window so the user can complete the
human credential step.

## Behavior

- Default mode: `WEBFA_AUTH_TAKEOVER=auto`
- Disabled mode: `WEBFA_AUTH_TAKEOVER=off`
- MCP tool list remains unchanged.
- `BrowserState.auth` reports whether an auth surface was detected and whether
  takeover opened a visible window.
- Password field values are removed from BrowserState.
- Cookies, storage, tokens, full DOM, and full HTML remain outside the
  agent-facing state.

## Manual Validation Targets

Recommended real-site validation:

1. DeepSeek: open `https://chat.deepseek.com/`, let WebFA show the login UI,
   user logs in, agent observes the chat home.
2. Xiaohongshu: open `https://www.xiaohongshu.com/user/profile`, user completes
   QR or phone login, agent reads visible profile notes only.
3. QQ Mail: open
   `https://wx.mail.qq.com/?cancel_login=true&from=get_ticket_fail`, user logs
   in, agent only confirms inbox/home unless explicitly approved to read mail.

These are manual validations because they require real user credentials,
QR-code scanning, verification, or site-side risk checks.

## Automated Verification

```text
python -m pytest tests/unit/test_auth_takeover.py tests/unit/test_agent_view.py tests/unit/test_browser_config.py tests/contract/test_mcp_security_contract.py -q
  -> 28 passed

python -m pytest -q
  -> 183 passed, 2 warnings

npm run typecheck:renderer
  -> passed

npm run typecheck:electron
  -> passed

python -m build
  -> built sdist and wheel
```
