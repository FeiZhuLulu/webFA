# WebFA Agent Validation Harness

This harness validates the current P10 public Agent surface:

```text
WebState + stable WebObjects + queryable observe + declared capabilities + semantic operations
```

Agents should read `AGENT_MANUAL.md` before validation. WebFA is not a Playwright wrapper, a selector API, a screenshot-coordinate controller, a site API wrapper, or an autonomous agent.

The public loop remains:

```text
external agent / MCP client
  -> webfa.open_url
  -> webfa.observe
  -> webfa.act
  -> webfa.observe
```

## Required Runtime Setup

Install project dependencies and ensure Google Chrome, Microsoft Edge, or another supported Chromium executable is installed:

```powershell
pip install -e ".[dev]"
npm install
webfa doctor
```

Set `WEBFA_CHROMIUM_EXECUTABLE` only when WebFA cannot discover a system Chromium installation.

Start the desktop stack:

```powershell
npm run dev
```

Or start only Runtime:

```powershell
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787
```

The MCP server is started by the MCP client with:

```powershell
python -m apps.runtime.mcp.server
```

Use this environment variable when the MCP client connects to a separately running Runtime:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
```

## Expected MCP Tools

By default the agent sees exactly:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

The agent must not see or send:

```text
click / double_click / type / press / focus
selector / XPath / locator
raw DOM / full HTML
evaluate / raw CDP / Playwright
cookies / storage / tokens / password values
site-specific business tools
```

Legacy transaction tools appear only when explicitly enabled with `WEBFA_ENABLE_LEGACY_TRANSACTION=1`; they are not part of browser validation.

## Level 0: REST WebObject Loop

Use:

```text
tests/fixtures/agent_validation_page.html
```

Expected flow:

```text
POST /v1/browser/web/open
POST /v1/browser/web/observe  { mode: "query", query: { capability: "set_value" } }
POST /v1/browser/web/act      { operation: "set_value", target: "obj_*", arguments: { value: "Fei" } }
POST /v1/browser/web/observe  { mode: "query", query: { role: "form" } }
POST /v1/browser/web/act      { operation: "submit", target: "obj_*" }
POST /v1/browser/web/observe  { mode: "query", query: { text_contains: "Hello Fei" } }
```

Automated test:

```powershell
pytest tests/integration/test_web_object_api.py -q
```

## Level 1: MCP Stdio WebObject Loop

Automated test:

```powershell
pytest tests/integration/test_mcp_stdio_browser.py -q
```

The test starts a real Runtime and MCP stdio server, verifies the five-tool schema, and runs:

```text
webfa.open_url
webfa.observe(query)
webfa.act(set_value)
webfa.observe(query)
webfa.act(submit)
webfa.observe(query)
```

It also verifies dialog recovery:

```text
webfa.act(activate)
  -> dialog_required
webfa.observe(query role=dialog)
webfa.act(dismiss)
webfa.observe(query)
```

## Level 2: External Agent Local Page

Recommended prompt:

```text
Use WebFA as your browser. Open the local validation page at <file-url>.
Find the field WebObject that declares set_value, set it to "Fei", find the form
that declares submit, submit it, then query for the result text.
Use only webfa.open_url, webfa.observe, and webfa.act.
Do not use click, type, press, selectors, coordinates, raw DOM, Playwright, CDP,
or site-specific APIs.
```

Pass condition:

```text
The agent reports "Hello Fei" from a WebObject returned by observe.
```

## Level 3: Structured Public Pages

Validate low-risk public pages such as:

```text
documentation pages
public repository search
public model search
articles
lists and tables
basic forms
```

The Agent should use:

- page mode for document overview;
- query mode to locate objects by role, name, capability, origin, or text;
- object mode for relations and range reads;
- changes mode after dynamic updates.

Do not perform account writes at this level.

## Level 4: Human Takeover and Persistent Profile

Manual flow:

```text
1. Open a site that requires authentication.
2. Observe authentication or request Human Takeover.
3. User completes login in the WebFA takeover surface.
4. Complete takeover and resume with observe.
5. Restart Runtime.
6. Open the site again and confirm profile state persists.
```

Also validate an opaque fixture:

```text
tests/fixtures/opaque_surface_page.html
```

Expected result:

```text
canvas -> opaque_surface -> request_human_takeover
```

WebFA must not fall back to screenshot-coordinate control.

## Level 5: Real Task Preflight

Use realistic pages but stop before irreversible final effects. For example:

```text
Open a repository creation form.
Set fields through semantic operations.
Inspect the final form state.
Stop before the final external write unless the safety layer explicitly approves it.
```

## Acceptance Gate

Run:

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

The public MCP test must prove:

```text
open_url -> observe WebObjects -> semantic act -> observe changes
```

No default Agent-facing request or response may require browser primitives, selectors, raw DOM, Playwright, or CDP.
