# Contributing

WebFA is a developer preview. Contributions should preserve the core product
boundary: WebFA is an agent-native browser runtime, not a site-specific API
wrapper and not an agent planner.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
npm install
```

## Checks

Run these before opening a pull request:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

## Product Rules

- Keep the default MCP surface to five browser tools.
- Do not expose raw Playwright, raw CDP, selectors, XPath, or evaluate.
- Do not add site-specific business tools such as `github.create_repo`.
- Do not return cookies, storage, tokens, passwords, or full DOM/HTML.
- Prefer generic page objects: URLs, forms, links, controls, lists, and blocks.
- Keep intelligence in the external agent, not inside WebFA.

## Documentation

When changing agent-facing behavior, update:

- `README.md`
- `AGENT_MANUAL.md`
- `docs/agent-entry-package.md`
- relevant files under `docs/agent-integrations/`

Avoid committing personal account names, local absolute paths, emails, tokens,
or raw website content from private sessions.
