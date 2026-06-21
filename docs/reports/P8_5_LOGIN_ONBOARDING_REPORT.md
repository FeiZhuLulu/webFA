# P8.5 Login/Profile Onboarding Report

## Goal

P8.5 adds a minimal login entry before public packaging so users can put
authenticated sessions into the default WebFA profile without asking an agent to
type passwords.

## Scope

Implemented:

- `webfa login github`
- `webfa login --url https://example.com/login`
- Manual visible login window using the default managed-chromium profile
- CLI status text showing site, profile, and profile path
- Unit coverage for target resolution and CLI command dispatch
- Documentation in README, agent entry package docs, and roadmap

Not implemented:

- No new MCP tools
- No site API wrappers
- No password/token capture
- No cookies/storage/token output
- No custom desktop visualizer yet
- No automatic login success detection

## Behavior

`webfa login` opens a visible WebFA-managed Chromium window. The user signs in
manually, including password, QR code, 2FA, or authorization screens. After the
user presses Enter in the CLI, WebFA closes the window and keeps the default
managed-chromium profile for later Runtime and MCP sessions.

The default MCP tool contract remains unchanged:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

## Automated Verification

Targeted tests:

```powershell
python -m pytest tests/unit/test_login.py tests/unit/test_cli_entrypoints.py tests/unit/test_mcp_config_generator.py tests/unit/test_runtime_process.py -q
```

Result:

```text
19 passed
```

Full project verification:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

Result:

```text
python -m pytest -q               -> 174 passed, 2 warnings
npm run typecheck:renderer        -> passed
npm run typecheck:electron        -> passed
python -m build                   -> built sdist and wheel
```

## Manual Validation

Recommended manual check:

```powershell
webfa login github
webfa status
```

Then ask an external MCP agent to:

```text
Open github.com with WebFA and observe whether the page is logged in.
```

Expected result: BrowserState shows the GitHub Dashboard or authenticated
navigation, not the public sign-in/sign-up page.
