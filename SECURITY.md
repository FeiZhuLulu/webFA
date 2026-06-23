# Security Policy

WebFA is a local agent browser runtime. It can operate real websites using the
local user's browser profile, so security issues should be treated seriously.

## Supported Status

Current status: developer preview.

The project is not yet a stable production browser, password manager, or
high-risk automation platform. Do not use it for unattended banking, payments,
account recovery, destructive admin actions, or sensitive mailbox workflows
without human supervision.

## Reporting Issues

Do not publish exploit details or private credentials in public issues.

For now, report security concerns by opening a minimal GitHub issue that says
you have a security concern and includes a non-sensitive contact method. Do not
include tokens, cookies, passwords, session storage, screenshots with secrets,
or private website content.

## Security Boundaries

WebFA should not expose these to agents:

- cookies
- localStorage or sessionStorage values
- tokens or authorization headers
- password values
- raw Chrome DevTools Protocol
- raw Playwright handles
- selector/XPath/evaluate escape hatches

Agents should authenticate through user-assisted auth takeover. WebFA should
not ask an agent to type passwords or one-time codes.

## Known Developer Preview Limitations

- The visible auth takeover window currently uses managed Chromium.
- All agents connected to the same Runtime share the default profile and login
  state unless users choose a separate `WEBFA_HOME`.
- Only one active agent should control the browser at a time; WebFA enforces a
  lease, but users should still avoid parallel high-risk tasks.
- Some websites may block headless or automated browser environments.
- Human confirmation for high-risk real-world writes is not complete yet.
